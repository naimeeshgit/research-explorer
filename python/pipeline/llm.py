"""Pluggable LLM layer. The provider is chosen from the model name:

    gemini-*  -> Google Gemini (google-genai SDK, GEMINI_API_KEY)
    claude-*  -> Anthropic (anthropic SDK, ANTHROPIC_API_KEY; optional, install `anthropic` to use)

Every call returns an LLMResult with normalized token usage so costs.py can price it.
"""
import random
import sys
import time
from dataclasses import dataclass, field

import config


@dataclass
class Usage:
    input_tokens: int = 0          # billed at the input rate (excludes cache reads)
    output_tokens: int = 0         # includes thinking tokens, which are billed as output
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class LLMResult:
    text: str
    ok: bool                       # finished normally (not truncated, blocked or refused)
    stop_reason: str
    usage: Usage = field(default_factory=Usage)


class LLMError(RuntimeError):
    pass


def provider_for(model: str) -> str:
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith("claude"):
        return "anthropic"
    raise LLMError(f"Don't know which provider serves {model!r}")


def check_key(model: str) -> None:
    p = provider_for(model)
    if p == "gemini" and not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is not set. Add it to .env first (get one at aistudio.google.com/apikey).")
    if p == "gemini" and config.GEMINI_API_KEY == config.OPENALEX_API_KEY:
        raise SystemExit("GEMINI_API_KEY in .env is the same as OPENALEX_API_KEY. Paste your Gemini key "
                         "(starts with 'AIza', from aistudio.google.com/apikey) into GEMINI_API_KEY.")
    if p == "anthropic" and not config.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY is not set. Add it to .env first.")


_last_call: dict[str, float] = {}


def _throttle(model: str) -> None:
    gap = config.LLM_MIN_SECONDS_BETWEEN_CALLS.get(model, 0)
    wait = gap - (time.monotonic() - _last_call.get(model, 0))
    if wait > 0:
        time.sleep(wait)
    _last_call[model] = time.monotonic()


def generate_json(model: str, system: str, user: str, schema: dict, max_tokens: int,
                  thinking: str | None = None) -> LLMResult:
    """One structured-output call. Retries rate limits and server errors with backoff."""
    check_key(model)
    fn = _gemini_json if provider_for(model) == "gemini" else _anthropic_json
    for attempt in range(6):
        _throttle(model)
        try:
            return fn(model, system, user, schema, max_tokens, thinking)
        except _Retryable as e:
            delay = min(2 ** attempt * 5 + random.uniform(0, 2), 120)
            print(f"    {model}: {e}; retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
    raise LLMError(f"{model}: gave up after repeated rate-limit/server errors")


class _Retryable(Exception):
    pass


# --- Gemini ------------------------------------------------------------------------------

_gemini_client = None


def _gemini_json(model, system, user, schema, max_tokens, thinking) -> LLMResult:
    global _gemini_client
    from google import genai
    from google.genai import errors, types

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_json_schema=schema,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),  # no tools; silences SDK warning
    )
    try:
        resp = _gemini_client.models.generate_content(model=model, contents=user, config=cfg)
    except errors.APIError as e:
        if e.code == 429 or (e.code or 0) >= 500:
            raise _Retryable(f"HTTP {e.code}") from e
        if e.code == 402:
            raise SystemExit(f"Gemini billing problem (402): {e.message}\n"
                             "Add prepaid credit at https://ai.studio/projects, or use a key from a project "
                             "without billing (free tier). See OWNER_MANUAL.md, section 1.") from e
        if e.code in (401, 403) or "API key" in str(e.message):
            raise SystemExit(f"Gemini rejected the API key ({e.code}: {e.message}).\n"
                             "Check GEMINI_API_KEY in .env: Gemini keys start with 'AIza' and are 39 characters. "
                             "Get one at aistudio.google.com/apikey.") from e
        raise LLMError(f"{model}: HTTP {e.code}: {e.message}") from e

    u = resp.usage_metadata
    prompt = (u.prompt_token_count or 0) if u else 0
    cached = (u.cached_content_token_count or 0) if u else 0
    usage = Usage(input_tokens=prompt - cached,
                  output_tokens=((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0,
                  cache_read_tokens=cached)
    cand = resp.candidates[0] if resp.candidates else None
    reason = cand.finish_reason.name if cand and cand.finish_reason else "NO_CANDIDATE"
    if resp.prompt_feedback and resp.prompt_feedback.block_reason:
        reason = f"BLOCKED_{resp.prompt_feedback.block_reason.name}"
    text = (resp.text or "") if cand else ""
    return LLMResult(text=text, ok=(reason == "STOP"), stop_reason=reason, usage=usage)


# --- Anthropic (optional) -----------------------------------------------------------------

_anthropic_client = None


def _anthropic_json(model, system, user, schema, max_tokens, thinking) -> LLMResult:
    global _anthropic_client
    try:
        import anthropic
    except ImportError as e:
        raise SystemExit("To use a claude-* model here, run: uv pip install anthropic") from e
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY,
                                                base_url=config.ANTHROPIC_BASE_URL, max_retries=0)
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if thinking:
        output_config["effort"] = thinking  # adaptive thinking is on by default on current models
    try:
        msg = _anthropic_client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
        raise _Retryable(type(e).__name__) from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"{model}: HTTP {e.status_code}: {e.message}") from e
    u = msg.usage
    usage = Usage(input_tokens=u.input_tokens or 0, output_tokens=u.output_tokens or 0,
                  cache_read_tokens=u.cache_read_input_tokens or 0,
                  cache_write_tokens=u.cache_creation_input_tokens or 0)
    text = "".join(b.text for b in msg.content if b.type == "text")
    reason = msg.stop_reason
    if reason == "refusal" and getattr(msg, "stop_details", None):
        reason = f"refusal:{msg.stop_details.category}"  # Haiku 5.5 has no server-side fallback
    return LLMResult(text=text, ok=msg.stop_reason == "end_turn", stop_reason=reason, usage=usage)
