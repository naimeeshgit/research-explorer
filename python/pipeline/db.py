"""SQLite schema and helpers. Raw data tables are never overwritten by derived data."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS faculty (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    area TEXT,
    homepage_url TEXT,
    scholar_url TEXT,              -- for human reviewers only; never fetched
    openalex_author_id TEXT,
    match_status TEXT CHECK (match_status IN ('confirmed', 'needs_review', 'not_found')),
    match_notes TEXT,
    media_json TEXT                -- reserved for future professor videos
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY,
    openalex_work_id TEXT NOT NULL UNIQUE,
    doi TEXT,
    title TEXT,
    title_normalized TEXT,
    publication_date TEXT,
    year INTEGER,
    type TEXT,
    venue TEXT,
    abstract TEXT,
    is_oa INTEGER,
    oa_pdf_url TEXT,
    landing_page_url TEXT,
    locations_json TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    faculty_id INTEGER NOT NULL REFERENCES faculty(id),
    author_position TEXT,
    PRIMARY KEY (paper_id, faculty_id)
);

CREATE TABLE IF NOT EXISTS paper_texts (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id),
    source TEXT CHECK (source IN ('oa_pdf', 'manual')),
    pdf_path TEXT,
    text TEXT,
    n_pages INTEGER,
    n_chars INTEGER,
    status TEXT CHECK (status IN ('ok', 'no_oa', 'download_failed', 'not_pdf',
                                  'extract_failed', 'blocked_by_robots')),
    error TEXT,
    extracted_at TEXT
);

CREATE TABLE IF NOT EXISTS paper_cards (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    card_json TEXT NOT NULL,
    basis TEXT CHECK (basis IN ('full_text', 'abstract_only')),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_cards_paper ON paper_cards(paper_id, id);

CREATE TABLE IF NOT EXISTS prof_profiles (
    id INTEGER PRIMARY KEY,
    faculty_id INTEGER NOT NULL REFERENCES faculty(id),
    profile_json TEXT NOT NULL,
    latest_paper_id INTEGER REFERENCES papers(id),
    based_on_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prof_profiles_faculty ON prof_profiles(faculty_id, id);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    batch INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Bookkeeping for Message Batches, so an interrupted run resumes instead of resubmitting.
CREATE TABLE IF NOT EXISTS card_batch_requests (
    custom_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    basis TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | failed
    submitted_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_batch_requests_batch ON card_batch_requests(batch_id, status);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    step TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stats_json TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def run(conn: sqlite3.Connection, step: str):
    """Record a pipeline step in `runs`. Yields a dict the step fills with stats."""
    cur = conn.execute("INSERT INTO runs (step, started_at) VALUES (?, ?)", (step, now()))
    run_id = cur.lastrowid
    conn.commit()
    stats: dict = {}
    try:
        yield stats
    except BaseException as e:
        stats["error"] = repr(e)
        raise
    finally:
        conn.execute(
            "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?",
            (now(), json.dumps(stats, default=str), run_id),
        )
        conn.commit()
