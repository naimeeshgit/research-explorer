"""Part 3: full text for every paper whose PDF is legally available.

Sources, in priority order:
  1. data/manual_pdfs/ + data/manual_pdfs.csv   (source='manual'; always wins)
  2. open-access PDF URLs from OpenAlex locations (source='oa_pdf')
  3. OpenAlex's paid content endpoint, only with --use-openalex-content (source='oa_pdf',
     file saved as data/pdfs/<W>_openalex.pdf)

Politeness: robots.txt is checked for every URL (including redirects), the User-Agent
carries CONTACT_EMAIL, and each domain gets at most 1 request per second.
"""
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import pymupdf
import httpx

import config
from pipeline import db, openalex, works

TIMEOUT = 30
MAX_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
MIN_CHARS_MULTIPAGE = 2000
PAGE_MARKER = "[[page {}]]"


# --- Polite HTTP ----------------------------------------------------------------------

class Fetcher:
    def __init__(self):
        self.client = httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=TIMEOUT,
                                   follow_redirects=False)
        self.last_hit: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser | None] = {}

    def _throttle(self, host: str, min_gap: float = config.MIN_SECONDS_PER_REQUEST_PER_DOMAIN):
        wait = min_gap - (time.monotonic() - self.last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.last_hit[host] = time.monotonic()

    def _robots_for(self, url: str) -> RobotFileParser | None:
        """Returns a parser, or None meaning 'allow everything'. Raises PermissionError when
        robots.txt forbids all access (401/403) or can't be read because of a server error."""
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            self._throttle(p.netloc)
            rp = RobotFileParser()
            try:
                r = self.client.get(origin + "/robots.txt", follow_redirects=True)
                code = r.status_code
            except httpx.HTTPError:
                code = None
            if code == 200:
                rp.parse(r.text.splitlines())
            elif code in (401, 403):
                rp.disallow_all = True
            elif code is not None and 400 <= code < 500:
                rp = None  # no robots.txt: everything allowed
            else:
                rp.disallow_all = True  # 5xx / unreachable: treat as temporarily disallowed
            self.robots[origin] = rp
        return self.robots[origin]

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return rp is None or rp.can_fetch(config.USER_AGENT, url)

    def crawl_delay(self, url: str) -> float:
        rp = self._robots_for(url)
        delay = rp.crawl_delay(config.USER_AGENT) if rp else None
        return max(float(delay or 0), config.MIN_SECONDS_PER_REQUEST_PER_DOMAIN)

    def download_pdf(self, url: str, dest, headers: dict | None = None) -> tuple[str, str | None]:
        """Download url to dest if it is really a PDF. Returns (status, error)."""
        for _ in range(MAX_REDIRECTS + 1):
            if urlparse(url).scheme not in ("http", "https"):
                return "download_failed", f"unsupported URL scheme: {url}"
            if not self.allowed(url):
                return "blocked_by_robots", f"robots.txt disallows {url}"
            self._throttle(urlparse(url).netloc, self.crawl_delay(url))
            try:
                with self.client.stream("GET", url, headers=headers or {}) as r:
                    if r.is_redirect:
                        url = urljoin(url, r.headers.get("location", ""))
                        continue
                    if r.status_code != 200:
                        return "download_failed", f"HTTP {r.status_code} from {url}"
                    ctype = r.headers.get("content-type", "").lower()
                    length = int(r.headers.get("content-length") or 0)
                    if length > MAX_BYTES:
                        return "download_failed", f"file too large ({length} bytes) at {url}"
                    if "html" in ctype:  # landing page, login wall or bot challenge
                        return "not_pdf", f"not a PDF (content-type {ctype}) at {url}"
                    chunks, size = [], 0
                    for chunk in r.iter_bytes():
                        if not chunks and len(chunk) >= 5 and b"%PDF" not in chunk[:1024]:
                            return "not_pdf", f"not a PDF (content-type {ctype or '?'}) at {url}"
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > MAX_BYTES:
                            return "download_failed", f"file larger than 50 MB at {url}"
                    data = b"".join(chunks)
            except httpx.HTTPError as e:
                return "download_failed", f"{type(e).__name__} at {url}: {e}"
            if b"%PDF" not in data[:1024]:
                return "not_pdf", f"not a PDF (content-type {ctype or '?'}) at {url}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return "ok", None
        return "download_failed", f"too many redirects from {url}"


# --- Text extraction ----------------------------------------------------------------------

EDGE_LINES = 2  # lines at the top and bottom of each page considered for header/footer removal


def _norm_line(line: str) -> str:
    """Key used to spot repeated headers/footers. Digits are ignored only on short lines
    ('Page 3 of 20', '1234'), so body lines that differ by a number are never merged."""
    s = line.strip().lower()
    return re.sub(r"\d+", "#", s) if len(s) < 40 else s


def _edge_indexes(lines: list[str]) -> list[int]:
    nonblank = [i for i, l in enumerate(lines) if l.strip()]
    return nonblank[:EDGE_LINES] + nonblank[-EDGE_LINES:]


def _repeated_edge_lines(pages: list[list[str]]) -> set[str]:
    """Keys of lines that sit at the top or bottom of at least half the pages (running
    heads, journal names, page numbers). Only used with >= 4 pages."""
    if len(pages) < 4:
        return set()
    counts = Counter()
    for lines in pages:
        counts.update({_norm_line(lines[i]) for i in _edge_indexes(lines) if len(lines[i].strip()) < 120})
    return {key for key, n in counts.items() if key and n >= max(3, 0.5 * len(pages))}


def _reflow(text: str) -> str:
    text = re.sub(r"(\w)-\n(\s*)([a-z])", r"\1\3", text)           # de-hyphenate across lines
    text = re.sub(r"(?<![.?!:;\n])\n(?=[a-z(])", " ", text)        # join broken sentence lines
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(pdf_path) -> tuple[str, int]:
    """Returns (text with [[page N]] markers, n_pages). Raises on unreadable PDFs."""
    with pymupdf.open(pdf_path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF is password-protected")
        pages = [page.get_text("text").splitlines() for page in doc]
    drop = _repeated_edge_lines(pages)
    parts = []
    for i, lines in enumerate(pages, start=1):
        edges = set(_edge_indexes(lines))
        kept = [l for j, l in enumerate(lines) if not (j in edges and _norm_line(l) in drop)]
        body = _reflow("\n".join(kept))
        parts.append(f"{PAGE_MARKER.format(i)}\n{body}")
    return "\n\n".join(parts), len(pages)


def body_chars(text: str) -> int:
    return len(re.sub(r"\[\[page \d+\]\]", "", text).strip())


# --- Storage -----------------------------------------------------------------------------

def save(conn, paper_id: int, source: str | None, pdf_path, status: str, error: str | None,
         text: str | None = None, n_pages: int | None = None) -> None:
    conn.execute(
        """INSERT INTO paper_texts (paper_id, source, pdf_path, text, n_pages, n_chars, status, error, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(paper_id) DO UPDATE SET source = excluded.source, pdf_path = excluded.pdf_path,
               text = excluded.text, n_pages = excluded.n_pages, n_chars = excluded.n_chars,
               status = excluded.status, error = excluded.error, extracted_at = excluded.extracted_at""",
        (paper_id, source, str(pdf_path.relative_to(config.ROOT)) if pdf_path else None, text, n_pages,
         len(text) if text else None, status, error, db.now()),
    )
    conn.commit()


def extract_and_save(conn, paper_id: int, source: str, pdf_path) -> str:
    try:
        text, n_pages = extract_text(pdf_path)
    except Exception as e:
        save(conn, paper_id, source, pdf_path, "extract_failed", f"{type(e).__name__}: {e}")
        return "extract_failed"
    if n_pages > 1 and body_chars(text) < MIN_CHARS_MULTIPAGE:
        save(conn, paper_id, source, pdf_path, "extract_failed",
             f"only {body_chars(text)} characters from {n_pages} pages; probably scanned", text, n_pages)
        return "extract_failed"
    save(conn, paper_id, source, pdf_path, "ok", None, text, n_pages)
    return "ok"


def candidate_urls(paper) -> list[str]:
    urls = [paper["oa_pdf_url"]] if paper["oa_pdf_url"] else []
    for loc in json.loads(paper["locations_json"] or "[]"):
        if loc.get("pdf_url"):
            urls.append(loc["pdf_url"])
    return list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))


# --- Manual PDFs ------------------------------------------------------------------------

def file_sha1(path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def attach_manual(conn) -> Counter:
    c = Counter()
    if not config.MANUAL_PDF_CSV.exists():
        return c
    with open(config.MANUAL_PDF_CSV, newline="", encoding="utf-8-sig") as f:
        rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]
    for r in rows:
        fname, ref = r.get("filename", ""), r.get("doi_or_openalex_id", "")
        if not fname or not ref:
            continue
        path = config.MANUAL_PDF_DIR / fname
        if not path.exists():
            print(f"  MANUAL missing file: {fname}")
            c["missing_file"] += 1
            continue
        wid = openalex.short_id(ref) if re.fullmatch(r"(https?://openalex\.org/)?[Ww]\d+", ref) else None
        if wid:
            paper = conn.execute("SELECT id FROM papers WHERE openalex_work_id = ?", (wid,)).fetchone()
        else:
            paper = conn.execute("SELECT id FROM papers WHERE doi = ? ORDER BY id LIMIT 1",
                                 (works.clean_doi(ref),)).fetchone()
        if not paper:
            print(f"  MANUAL no matching paper for {fname} -> {ref}")
            c["no_match"] += 1
            continue
        # Skip if this exact file was already processed for this paper.
        rel = str(path.relative_to(config.ROOT))
        prev = conn.execute("SELECT source, pdf_path FROM paper_texts WHERE paper_id = ?",
                            (paper["id"],)).fetchone()
        sha = file_sha1(path)
        if prev and prev["source"] == "manual" and prev["pdf_path"] == rel and _manual_sha(conn, paper["id"]) == sha:
            c["unchanged"] += 1
            continue
        status = extract_and_save(conn, paper["id"], "manual", path)
        _set_manual_sha(conn, paper["id"], sha)
        c[f"manual_{status}"] += 1
        print(f"  MANUAL {fname} -> paper {paper['id']}: {status}")
    return c


# The sha of the processed manual file is kept in a tiny side table so a replaced file is
# re-extracted. It is bookkeeping only, not raw or derived data.
def _manual_sha(conn, paper_id: int) -> str | None:
    conn.execute("CREATE TABLE IF NOT EXISTS manual_pdf_hashes (paper_id INTEGER PRIMARY KEY, sha1 TEXT)")
    row = conn.execute("SELECT sha1 FROM manual_pdf_hashes WHERE paper_id = ?", (paper_id,)).fetchone()
    return row["sha1"] if row else None


def _set_manual_sha(conn, paper_id: int, sha: str) -> None:
    _manual_sha(conn, paper_id)
    conn.execute("INSERT INTO manual_pdf_hashes (paper_id, sha1) VALUES (?, ?) "
                 "ON CONFLICT(paper_id) DO UPDATE SET sha1 = excluded.sha1", (paper_id, sha))
    conn.commit()


# --- Main step ---------------------------------------------------------------------------

def run(use_openalex_content: bool = False, retry_failed: bool = False, yes: bool = False,
        limit: int | None = None) -> None:
    conn = db.connect()
    fetcher = Fetcher()
    totals = Counter()

    with db.run(conn, "fulltext") as stats:
        totals.update(attach_manual(conn))

        cutoff = (datetime.now(timezone.utc) - timedelta(days=config.FULLTEXT_RETRY_DAYS)).isoformat()
        papers = conn.execute("""
            SELECT p.id, p.openalex_work_id, p.title, p.oa_pdf_url, p.locations_json, p.raw_json,
                   t.status AS prev_status, t.extracted_at AS prev_at, t.pdf_path AS prev_path
            FROM papers p
            LEFT JOIN paper_texts t ON t.paper_id = p.id
            WHERE p.id IN (SELECT paper_id FROM paper_authors)
              AND (t.status IS NULL OR t.status != 'ok')
            ORDER BY p.id""").fetchall()

        todo = []
        for p in papers:
            urls = candidate_urls(p)
            recently_failed = (p["prev_status"] not in (None, "no_oa") and p["prev_at"] and p["prev_at"] > cutoff)
            if urls and recently_failed and not retry_failed:
                totals["skipped_recent_failure"] += 1
                continue
            todo.append((p, urls))
        if limit:
            todo = todo[:limit]

        n_dl = sum(1 for _, u in todo if u)
        print(f"Papers without full text: {len(papers)}  |  to try now: {n_dl} with OA PDF URLs  |  "
              f"skipped (failed < {config.FULLTEXT_RETRY_DAYS} days ago): {totals['skipped_recent_failure']}")

        for i, (p, urls) in enumerate(todo, start=1):
            if not urls:
                save(conn, p["id"], None, None, "no_oa", "no open-access PDF URL in OpenAlex")
                totals["no_oa"] += 1
                continue
            dest = config.PDF_DIR / f"{p['openalex_work_id']}.pdf"
            errors, status = [], "download_failed"
            if dest.exists() and dest.read_bytes()[:1024].find(b"%PDF") >= 0:
                status = "ok"  # downloaded on an earlier run; just re-extract
            else:
                worst = None
                for url in urls:
                    status, err = fetcher.download_pdf(url, dest)
                    if status == "ok":
                        break
                    errors.append(err)
                    worst = worst or status
                if status != "ok":
                    status = worst
            if status == "ok":
                status = extract_and_save(conn, p["id"], "oa_pdf", dest)
            else:
                save(conn, p["id"], "oa_pdf", None, status, " | ".join(errors)[:2000])
            totals[status] += 1
            print(f"  [{i}/{len(todo)}] {status:<17} {p['openalex_work_id']}  {(p['title'] or '')[:60]}")

        if use_openalex_content:
            totals.update(fetch_openalex_content(conn, yes))

        stats.update(dict(totals))

    print()
    print("This run: " + ", ".join(f"{k} {v}" for k, v in sorted(totals.items())) if totals else "Nothing to do.")
    report(conn)


def fetch_openalex_content(conn, yes: bool) -> Counter:
    """Paid fallback: OpenAlex's cached PDFs ($0.01 each), for papers still without text."""
    c = Counter()
    rows = conn.execute("""
        SELECT p.id, p.openalex_work_id, p.raw_json FROM papers p
        LEFT JOIN paper_texts t ON t.paper_id = p.id
        WHERE p.id IN (SELECT paper_id FROM paper_authors) AND (t.status IS NULL OR t.status != 'ok')""").fetchall()
    todo = []
    for r in rows:
        work = json.loads(r["raw_json"])
        url = (work.get("content_urls") or {}).get("pdf")
        if (work.get("has_content") or {}).get("pdf") and url:
            todo.append((r, url))
    rows = todo
    est = len(rows) * config.OPENALEX_CONTENT_USD_PER_PDF
    print(f"\nOpenAlex content endpoint: {len(rows)} papers have a cached PDF; estimated cost ${est:.2f}")
    if not rows:
        return c
    if not yes:
        print("Re-run with --use-openalex-content --yes to download them.")
        return c
    if not config.OPENALEX_API_KEY:
        print("OPENALEX_API_KEY is required for the content endpoint.")
        return c
    fetcher = Fetcher()
    for r, url in rows:
        dest = config.PDF_DIR / f"{r['openalex_work_id']}_openalex.pdf"
        status, err = fetcher.download_pdf(url, dest, headers={"Authorization": f"Bearer {config.OPENALEX_API_KEY}"})
        if status == "ok":
            status = extract_and_save(conn, r["id"], "oa_pdf", dest)
        else:
            save(conn, r["id"], "oa_pdf", None, status, f"openalex content: {err}")
        c[f"openalex_content_{status}"] += 1
        print(f"  openalex content {status:<15} {r['openalex_work_id']}")
    return c


def report(conn) -> None:
    by_status = conn.execute("""
        SELECT COALESCE(t.status, 'not_attempted') s, COUNT(*) n FROM papers p
        LEFT JOIN paper_texts t ON t.paper_id = p.id
        WHERE p.id IN (SELECT paper_id FROM paper_authors) GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    total = sum(r["n"] for r in by_status)
    print(f"\nFull-text status ({total} papers):")
    for r in by_status:
        print(f"  {r['s']:<18} {r['n']:>6}  {100 * r['n'] / total:5.1f}%")

    rows = conn.execute("""
        SELECT f.name, COUNT(p.id) n, SUM(t.status = 'ok') ok, SUM(t.status = 'ok' AND t.source = 'manual') manual,
               SUM(t.status != 'ok' AND p.abstract IS NULL) no_text
        FROM faculty f JOIN paper_authors pa ON pa.faculty_id = f.id JOIN papers p ON p.id = pa.paper_id
        LEFT JOIN paper_texts t ON t.paper_id = p.id
        WHERE f.match_status = 'confirmed' GROUP BY f.id ORDER BY f.name""").fetchall()
    print(f"\n{'professor':<35} {'papers':>6} {'full text':>10} {'manual':>7} {'no text, no abstract':>21}")
    out = []
    for r in rows:
        ok = r["ok"] or 0
        print(f"{r['name']:<35} {r['n']:>6} {ok:>4} ({100 * ok / r['n']:3.0f}%) {r['manual'] or 0:>7} {r['no_text'] or 0:>21}")
        out.append({"name": r["name"], "papers": r["n"], "full_text": ok,
                    "pct_full_text": round(100 * ok / r["n"], 1), "manual": r["manual"] or 0,
                    "no_text_no_abstract": r["no_text"] or 0})
    config.REPORTS_DIR.mkdir(exist_ok=True)
    with open(config.REPORTS_DIR / "fulltext_coverage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["name"])
        w.writeheader()
        w.writerows(out)
    fails = conn.execute("""SELECT t.status, t.error FROM paper_texts t
                            WHERE t.status NOT IN ('ok', 'no_oa') AND t.error IS NOT NULL""").fetchall()
    if fails:
        hosts = Counter()
        for f_ in fails:
            m = re.search(r"https?://([^/\s]+)", f_["error"])
            hosts[(f_["status"], m.group(1) if m else "?")] += 1
        print("\nMost common failures (status, host):")
        for (s, h), n in hosts.most_common(8):
            print(f"  {n:>4}  {s:<18} {h}")
    print("\nReport: reports/fulltext_coverage.csv")


def show(conn, ref: str, chars: int = 3000) -> None:
    """Print the start of one paper's extracted text (paper id or OpenAlex W id)."""
    col = "p.id" if ref.isdigit() else "p.openalex_work_id"
    val = int(ref) if ref.isdigit() else openalex.short_id(ref)
    if ref == "random":
        row = conn.execute("""SELECT p.id, p.openalex_work_id, p.title, t.* FROM papers p JOIN paper_texts t
                              ON t.paper_id = p.id WHERE t.status = 'ok' ORDER BY RANDOM() LIMIT 1""").fetchone()
    else:
        row = conn.execute(f"""SELECT p.id, p.openalex_work_id, p.title, t.* FROM papers p
                               LEFT JOIN paper_texts t ON t.paper_id = p.id WHERE {col} = ?""", (val,)).fetchone()
    if not row:
        print("No such paper.")
        return
    print(f"{row['openalex_work_id']} (paper {row['id']}): {row['title']}")
    print(f"status={row['status']} source={row['source']} pages={row['n_pages']} chars={row['n_chars']} "
          f"pdf={row['pdf_path']}")
    if row["error"]:
        print(f"error: {row['error']}")
    if row["text"]:
        print("-" * 80)
        print(row["text"][:chars])
