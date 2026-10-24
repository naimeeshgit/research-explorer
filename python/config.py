"""Central configuration. Secrets live in .env; everything else is here."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# --- Secrets -----------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Optional: only needed if you point a *_MODEL below at a claude-* model.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Explicit so a stray ANTHROPIC_BASE_URL in the shell can't reroute calls.
ANTHROPIC_BASE_URL = os.getenv("EXPLORER_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
USER_AGENT = f"isb-research-explorer/0.1 (mailto:{CONTACT_EMAIL or 'unset'})"

# --- Models (one per job) ------------------------------------------------------
# Pluggable: any "gemini-*" or "claude-*" model works (see pipeline/llm.py).
# Gemini IDs and prices checked against ai.google.dev on 2026-09-28.
# Claude IDs and prices from the claude-api reference, cached 2026-10-06.
# 2026-10-20: cards moved to Claude Haiku 5.5 (the Gemini free tier hit its daily cap and
# then started returning 402). Gemini comparison: reports/card_model_comparison.md.
CARD_MODEL = "claude-haiku-5-5"
CARD_MODEL_CANDIDATES = ["claude-haiku-5-5", "claude-sonnet-5-5"]
PROFILE_MODEL = "gemini-3.8-flash"
CHAT_MODEL = "gemini-3.8-flash"
EVAL_MODEL = "gemini-3.8-flash"  # must differ from CARD_MODEL

# Thinking level per model (None = the model's default). Thinking tokens are billed as output.
# For claude-* models this is output_config.effort; Haiku 5.5 thinks adaptively and defaults to "medium".
THINKING_LEVEL = {"gemini-3.1-flash-lite": None, "gemini-3.8-flash": "low", "claude-haiku-5-5": "medium"}

# Pause between calls to the same model. The Gemini free tier allows roughly 10-15
# requests per minute on Flash models; set these to 0 on a paid tier.
LLM_MIN_SECONDS_BETWEEN_CALLS = {"gemini-3.1-flash-lite": 4.5, "gemini-3.8-flash": 6.5, "claude-haiku-5-5": 0}

# --- Prices: USD per million tokens (paid tier). Edit to match the current price list.
# On the Gemini free tier calls cost $0, but Google may use the data to improve its products.
PRICES = {
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50, "cache_read": 0.025, "cache_write": 0.0},
    # 3.8 Flash doubles to $1.50 / $7.50 on 2027-01-01.
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75, "cache_read": 0.075, "cache_write": 0.0},
    # Haiku 5.5: prompts up to 100K tokens; above that $0.50 / $2.50. Cache prices assumed at the usual 1.25x / 0.1x.
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
}
BATCH_DISCOUNT = 0.5  # not used by the Gemini MVP, which calls models synchronously

# --- Prompt versions -----------------------------------------------------------
CARD_PROMPT_VERSION = "card_v3"  # v3: states the 25-word one_liner limit (Haiku 5.5 overran it). v2: v1 marked method/data "Not stated" on abstracts that name them
PROFILE_PROMPT_VERSION = "profile_v1"
CHAT_PROMPT_VERSION = "chat_system_v1"

# --- Paths ---------------------------------------------------------------------
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("EXPLORER_DB", DATA_DIR / "explorer.db"))
FACULTY_CSV = Path(os.getenv("EXPLORER_FACULTY_CSV", DATA_DIR / "faculty.csv"))
MANUAL_PDF_DIR = DATA_DIR / "manual_pdfs"
MANUAL_PDF_CSV = DATA_DIR / "manual_pdfs.csv"
PDF_DIR = DATA_DIR / "pdfs"
INDEX_DIR = DATA_DIR / "index"
CACHE_DIR = DATA_DIR / "cache"
PROMPTS_DIR = ROOT / "prompts"
REPORTS_DIR = ROOT / "reports"

# --- OpenAlex ------------------------------------------------------------------
OPENALEX_BASE = "https://api.openalex.org"
# Looked up in Part 1 via /institutions?search=Indian School of Business.
# Only one record exists: Indian School of Business, Hyderabad, IN (covers both campuses).
ISB_INSTITUTION_IDS = ["I122328836"]
# Docs (Sep 2026): per_page max is 100; 200 is deprecated legacy behaviour.
OPENALEX_PER_PAGE = 100
# Cache raw OpenAlex responses on disk during development. Set 0 to disable.
OPENALEX_CACHE_TTL_DAYS = 7
MIN_SECONDS_PER_REQUEST_PER_DOMAIN = 1.0

# --- Faculty matching ------------------------------------------------------------
MATCH_STRONG_NAME_SIM = 0.90   # rapidfuzz similarity (0-1) needed for a strong candidate
MATCH_MIN_WORKS = 3            # a strong candidate needs at least this many works
MATCH_MAX_CANDIDATES = 5       # candidates kept in match_notes / report
POSSIBLY_MISSING_MIN_WORKS = 5

# --- Cards (Part 4) ----------------------------------------------------------------
CARD_MAX_TOKENS = 8000           # output cap; cards are ~1k tokens, the rest is headroom for thinking
CARD_EST_OUTPUT_TOKENS = 1200    # used only for the pre-run cost estimate
CHARS_PER_TOKEN = 3.5            # rough estimate when not using the token-counting API
# Input-token ceiling per model (context window minus room for output). Longer papers
# are skipped and listed, never truncated.
# Gemini Flash context assumed to be 1M tokens (not stated on the models page); a paper
# over the limit gets an API error and is listed, never truncated.
MODEL_INPUT_LIMIT = {"gemini-3.1-flash-lite": 900_000, "gemini-3.8-flash": 900_000,
                     "claude-haiku-5-5": 900_000, "claude-sonnet-5-5": 900_000, "claude-opus-5-5": 900_000,
                     "claude-haiku-4-5-20251001": 180_000, "claude-sonnet-5": 900_000}

# --- Full text (Part 3) -------------------------------------------------------------
# Failed downloads are retried only after this many days (or with --retry-failed).
FULLTEXT_RETRY_DAYS = 7
# OpenAlex's paid PDF endpoint; used only with --use-openalex-content.
OPENALEX_CONTENT_USD_PER_PDF = 0.01

# --- Works (Part 2) --------------------------------------------------------------
WORK_TYPES_ALLOWED = ["article", "preprint", "review", "book", "book-chapter"]
