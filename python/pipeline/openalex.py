"""Small OpenAlex client: API key on every request, polite User-Agent, 1 req/s,
exponential backoff on 429/5xx, cursor pagination, and an on-disk response cache.

Cost notes (help.openalex.org, Sep 2026): singleton lookups are free, list+filter
calls cost $0.0001, search calls $0.001. per_page max is 100. Prefer filtering by ID.
"""
import hashlib
import json
import random
import re
import sys
import time
from typing import Iterator
from urllib.parse import urlencode

import httpx

import config

_last_request_at = 0.0
_warned_no_key = False
spent_usd = 0.0  # running total reported by OpenAlex's meta.cost_usd this process


class OpenAlexError(RuntimeError):
    pass


def short_id(openalex_id: str | None) -> str | None:
    """'https://openalex.org/A123' -> 'A123'."""
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1].strip().upper()


def split_ids(value: str | None) -> list[str]:
    """'A1|A2', 'A1, A2' or full URLs -> ['A1', 'A2'] (deduplicated, order kept)."""
    parts = re.split(r"[|,;\s]+", value or "")
    return list(dict.fromkeys(short_id(p) for p in parts if p.strip()))


def _cache_path(path: str, params: dict):
    key = path + "?" + urlencode(sorted(params.items()))
    return config.CACHE_DIR / "openalex" / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def _throttle():
    global _last_request_at
    wait = config.MIN_SECONDS_PER_REQUEST_PER_DOMAIN - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def get(path: str, params: dict | None = None, use_cache: bool = True, max_retries: int = 6) -> dict:
    """GET an OpenAlex endpoint and return parsed JSON. `path` like '/authors'."""
    global _warned_no_key, spent_usd
    params = dict(params or {})

    cache_file = _cache_path(path, params)
    ttl = config.OPENALEX_CACHE_TTL_DAYS * 86400
    if use_cache and ttl > 0 and cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
        return json.loads(cache_file.read_text())

    headers = {"User-Agent": config.USER_AGENT}
    if config.OPENALEX_API_KEY:
        headers["Authorization"] = f"Bearer {config.OPENALEX_API_KEY}"
    if not _warned_no_key:
        _warned_no_key = True
        if not config.OPENALEX_API_KEY:
            print("WARNING: OPENALEX_API_KEY is not set; using the small keyless budget.", file=sys.stderr)
        if not config.CONTACT_EMAIL:
            print("WARNING: CONTACT_EMAIL is not set; set it in .env for the User-Agent.", file=sys.stderr)

    url = config.OPENALEX_BASE + path
    for attempt in range(max_retries):
        _throttle()
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=60)
        except httpx.TransportError as e:
            err = f"network error: {e}"
        else:
            if resp.status_code == 200:
                data = resp.json()
                spent_usd += float((data.get("meta") or {}).get("cost_usd") or 0)
                if use_cache and ttl > 0:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(data))
                return data
            if resp.status_code == 404:
                raise OpenAlexError(f"404 Not Found: {path}")
            if resp.status_code != 429 and resp.status_code < 500:
                raise OpenAlexError(f"HTTP {resp.status_code} for {path}: {resp.text[:300]}")
            err = f"HTTP {resp.status_code}"
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if resp.status_code == 429 and remaining is not None and float(remaining) <= 0:
                raise OpenAlexError("OpenAlex daily budget exhausted (429). Try again after midnight UTC.")
        delay = min(2 ** attempt + random.uniform(0, 1), 60)
        print(f"  OpenAlex {err}; retry {attempt + 1}/{max_retries} in {delay:.0f}s", file=sys.stderr)
        time.sleep(delay)
    raise OpenAlexError(f"Giving up on {path} after {max_retries} attempts")


def iterate(path: str, params: dict | None = None, use_cache: bool = True) -> Iterator[dict]:
    """Yield every result of a list endpoint using cursor pagination."""
    params = dict(params or {})
    params["per_page"] = config.OPENALEX_PER_PAGE
    cursor = "*"
    while cursor:
        page = get(path, {**params, "cursor": cursor}, use_cache=use_cache)
        results = page.get("results") or []
        yield from results
        cursor = (page.get("meta") or {}).get("next_cursor")
        if not results:
            break


def get_author(author_id: str, use_cache: bool = True) -> dict:
    """Singleton lookup (free)."""
    return get(f"/authors/{short_id(author_id)}", use_cache=use_cache)
