# ISB Research Explorer: data pipeline (Python)

> **Status (2026-10-24):** the website moved to Next.js at the repo root and reads
> `content/*.json` (see `../README.md`). The Streamlit app was removed. This folder is kept for
> fetching faculty and paper metadata from OpenAlex and downloading open-access PDFs; turn its
> database into site content with `python3 python/scripts/export_content.py`. Summaries are no
> longer generated through LLM APIs, so the `cards` step is retired. Run commands from this
> `python/` folder.

## Original notes (Gemini MVP)

A local tool for exploring ISB faculty research: topic search, professor pages, and a
cited "explain this paper" chat. See `BUILD_PROMPT.md` for the full plan. Built so far:
Parts 1–4 (faculty, paper metadata, full text, paper cards).

**Your to-do list and open decisions are in [OWNER_MANUAL.md](OWNER_MANUAL.md).**

This is the low-cost copy of `../isb-research-explorer`. It is the same pipeline, but the
AI calls go through a pluggable layer (`pipeline/llm.py`) that defaults to cheap Gemini
models:

| Job | Model (`config.py`) | Paid price per 1M tokens (in / out) |
|---|---|---|
| Paper cards | `gemini-3.1-flash-lite` | $0.25 / $1.50 |
| Card comparison, profiles, chat, eval | `gemini-3.8-flash` | $0.75 / $3.75 (doubles on 2027-01-01) |

Any `gemini-*` or `claude-*` model ID works in any `*_MODEL` setting. Claude models need
`uv pip install anthropic` and an `ANTHROPIC_API_KEY`.

**Free tier.** A Gemini key from AI Studio works with no billing set up, and calls cost $0.
The limits are about 10–15 requests per minute, so the pipeline pauses between calls
(`LLM_MIN_SECONDS_BETWEEN_CALLS`), and there is a daily request cap. On the free tier,
Google may use prompts and responses to improve its products. The paper texts are open
access, but turn on billing before sending anything that isn't public.

Differences from the Claude version:

- Cards are generated one call at a time and saved as they go. There is no Message
  Batches step, so Ctrl-C and re-run is always safe.
- The chat (Part 7) can't use Claude's built-in citations. It will instead have the model
  quote the paper, and code will check each quote against the text before showing it.

## Setup

Requires Python 3.11+ (tested on 3.12).

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
cp .env.example .env   # then fill in the three values
```

`.env` needs `GEMINI_API_KEY` (free, from aistudio.google.com/apikey), `OPENALEX_API_KEY`
(free, from openalex.org/settings/api) and `CONTACT_EMAIL` (sent in the User-Agent to the
sites we fetch from).

## Step 1: faculty

1. Copy `data/faculty.template.csv` to `data/faculty.csv` and list the faculty. Only `name`
   is required. If you know someone's OpenAlex ID (e.g. `A5012345678` or the full
   `https://openalex.org/A…` URL), put it in `openalex_author_id`. It will be trusted as is.
   If OpenAlex has split one person into several profiles, list them all: `A123|A456`.
2. Run:
   ```bash
   .venv/bin/python -m pipeline faculty
   ```
3. Review `reports/faculty_resolution.csv`. It lists `needs_review` and `not_found` rows
   first, one row per candidate, with affiliations, ISB years, works count and an
   OpenAlex link. Paste the right ID into `faculty.csv` and re-run the step.
4. Look through `reports/possibly_missing_faculty.csv`. These are ISB-affiliated OpenAlex
   authors with 5 or more works who aren't matched to anyone in your CSV. Many of them
   are alumni, PhD students or visiting co-authors, so nothing is added automatically.

## Step 2: works

```bash
.venv/bin/python -m pipeline works
```

This fetches every work for each confirmed professor, stores the full OpenAlex JSON, and
links each paper to every ISB professor on it. It keeps only the types in
`WORK_TYPES_ALLOWED` (`config.py`) and prints the types it skipped. It then prints
papers per professor, the share with an abstract and with an open-access PDF URL, and the
5 most recent papers for 3 random professors to check against their homepages. The same
table is written to `reports/works_summary.csv`. To re-check particular people without
fetching:

```bash
.venv/bin/python -m pipeline works --report-only --spot-check "Jane Doe" "John Roe"
```

Journal, SSRN and working-paper versions of the same paper are stored as separate rows on
purpose. They are merged in a later version.

## Step 3: full text

```bash
.venv/bin/python -m pipeline fulltext
```

This downloads open-access PDFs for linked papers. It checks robots.txt first, sends your
contact email in the User-Agent, waits at least 1 second between requests to the same
site, gives up after 30 seconds, and skips files over 50 MB. It only accepts real PDFs, so
HTML landing pages are recorded as `not_pdf`. The text is extracted with `[[page N]]`
markers. Every attempt is recorded in `paper_texts` with a status and error. Papers
already `ok` are skipped. Failed downloads are retried after 7 days
(`FULLTEXT_RETRY_DAYS`), or right away with `--retry-failed`.

**PDFs from faculty.** Put the file in `data/manual_pdfs/` and add a row to
`data/manual_pdfs.csv`:

```csv
filename,doi_or_openalex_id
tantri_2025_zombie_lending.pdf,10.1017/S0022109024000000
chowdhry_wp.pdf,W4390000000
```

A manual PDF always replaces a downloaded one. If you replace the file later, it is
re-extracted.

**Paid OpenAlex PDFs** ($0.01 each) are off by default. To see how many are available,
run `--use-openalex-content`. Add `--yes` to actually buy them.

To check the output:

```bash
.venv/bin/python -m pipeline fulltext --report-only     # counts by status, % per professor
.venv/bin/python -m pipeline fulltext --show random     # print one extracted text
.venv/bin/python -m pipeline fulltext --show W2012345678
```

## Step 4: paper cards

The model writes one structured summary card per paper from its full text, or from the
abstract when that's all there is, and each card is labelled with which one it used. The
prompt is `prompts/card_v1.md`. Papers with neither are listed in
`reports/cards_skipped.csv`. Reference lists are removed only when they are detected
reliably, and the body of a paper is never truncated. A paper too long for the model is
skipped and listed.

1. **Compare models first** (10 calls: a few cents on a paid tier, $0 on the free tier):
   ```bash
   .venv/bin/python -m pipeline cards --sample 5 --compare
   ```
   Read `reports/card_model_comparison.md`. For each paper it shows the Flash-Lite and
   Flash cards side by side, the cost of each, and two automatic flags: numbers that don't
   appear in the source, and which fields say "Not stated". Keep `CARD_MODEL` as
   Flash-Lite unless its cards add facts, miss key findings or break the "Not stated" rule.
2. **Estimate the full run.** This sends nothing:
   ```bash
   .venv/bin/python -m pipeline cards
   ```
3. **Run it:**
   ```bash
   .venv/bin/python -m pipeline cards --yes
   ```
   Each card is saved as soon as it arrives. On the free tier, about 230 papers take
   15–20 minutes because of the pause between calls. An invalid or cut-off card is
   retried once, papers that still fail are retried on the next run, and a paper whose
   input hasn't changed is never sent again. If you hit the daily free-tier cap, re-run
   tomorrow and it continues where it stopped.
4. **Spot-check** 20 random cards next to their sources (also written to
   `reports/card_spotcheck.md`):
   ```bash
   .venv/bin/python -m pipeline cards --review 20
   ```

Other commands:

```bash
.venv/bin/python -m pipeline institutions   # show the OpenAlex institution candidates for ISB
.venv/bin/python -m pipeline faculty --no-cache
.venv/bin/python -m pipeline costs          # LLM spend so far
```

OpenAlex responses are cached in `data/cache/openalex/` for 7 days
(`OPENALEX_CACHE_TTL_DAYS` in `config.py`), so a re-run costs nothing.
