# Build Prompt — ISB Research Explorer (MVP)

## How to use this prompt

This is a multi-part build plan for an AI coding agent such as Claude Code, Cursor, or Codex. Save this file as `BUILD_PROMPT.md` in an empty folder, then tell the agent:

> Read BUILD_PROMPT.md. Complete Part 0 and Part 1 only. When Part 1's acceptance checks pass, stop and show me the results.

After that, continue one part at a time ("Now do Part 2"). Each part ends with acceptance checks, and the agent should not move on until they pass. Part 0 applies to every part.

Before you start, you need three things:

1. An Anthropic API key.
2. A free OpenAlex API key from openalex.org.
3. `data/faculty.csv`. The template is in Part 1.

## Part 0 — Context, rules, and architecture (applies to every part)

### What you are building

You are building a local tool that lets ISB (Indian School of Business) students explore ISB faculty research. It has three features:

1. Topic search. A student types a topic and gets relevant papers and professors.
2. Professor page. Shows a summary of the professor's overall research and a summary of their latest paper.
3. Explain this paper. A plain-English chat about one paper, with every claim cited to the paper's text.

The first demo audience is the professors themselves, so accuracy about their work matters more than anything else.

### Non-negotiable rules

1. Faithfulness. Everything the system says about a paper must come from that paper's text, or from its abstract with a clear label saying so. Prompts must forbid invented facts, and the chat must use citations.
2. Raw data is the source of truth. Store the raw metadata (the full OpenAlex JSON) and the extracted text once. Cards, profiles, and indexes are derived from that raw data. Version each derived item by `model` and `prompt_version`, and make sure everything derived can be rebuilt from the raw data with one command. Never overwrite raw data with generated data.
3. Open sources only. Get metadata from the OpenAlex API. Get full text only from open-access URLs, or from PDFs the user places in `data/manual_pdfs/`. Never scrape Google Scholar. Respect robots.txt, include the contact email in the User-Agent, and make at most 1 request per second to any domain.
4. Idempotent and resumable. Every pipeline step must be safe to re-run. It skips work that is already done and never pays twice for the same LLM output.
5. Keep it small. Use Python 3.11+, SQLite, Streamlit, a local embedding model, and numpy. Do not use a vector database, Docker, any web framework beyond Streamlit, or LangChain/LlamaIndex. The whole thing runs on a laptop.
6. Check the docs, not your memory. API details change. Before writing code against OpenAlex or the Anthropic API, read the current docs (developers.openalex.org / help.openalex.org, and docs.claude.com). Where they differ from this prompt, follow the docs.
7. Log LLM cost. Record the token usage from every Anthropic response in the `llm_calls` table, and make it possible to print total spend.

### Stack

* `httpx` (or `requests`) with retries and backoff
* `pymupdf` to extract text from PDFs
* `anthropic` Python SDK
* `sentence-transformers` with `BAAI/bge-small-en-v1.5` for embeddings
* `rank-bm25` for keyword search
* `rapidfuzz` for name matching
* `pydantic` for schema validation
* `streamlit` for the UI
* `python-dotenv` for config

### Configuration

`.env` holds the secrets:

```
ANTHROPIC_API_KEY=
OPENALEX_API_KEY=
CONTACT_EMAIL=
```

`config.py` holds:

* Model names, set separately for each job:
  * `CARD_MODEL`: the candidates are `claude-haiku-4-5-20251001` and `claude-sonnet-5`. The model comparison in Part 4 decides which one to use. Default to Haiku until then.
  * `PROFILE_MODEL` and `CHAT_MODEL`: `claude-sonnet-5`.
  * `EVAL_MODEL`: `claude-sonnet-5`. The eval checks the cards, so it must not be the same model that wrote them.
* Prices. Per-million-token prices, editable by the user.
* Prompt versions.
* Paths.
* The ISB institution ID(s). You look these up in Part 1.

### Repository layout

```
isb-research-explorer/
  BUILD_PROMPT.md
  .env.example
  config.py
  requirements.txt
  README.md
  data/
    faculty.csv          # provided by the user
    manual_pdfs/         # PDFs shared by faculty
    manual_pdfs.csv      # maps each manual PDF to a DOI or OpenAlex work ID
    pdfs/                # downloaded open-access PDFs
    index/               # embeddings + BM25 artifacts
    explorer.db          # SQLite database
  prompts/
    card_v1.md
    profile_v1.md
    chat_system_v1.md
  pipeline/
    __main__.py          # CLI: python -m pipeline <step>
    db.py  openalex.py  faculty.py  works.py  fulltext.py
    cards.py  profiles.py  index.py  costs.py
  app/
    app.py  search.py  chat.py
  evals/
    search_queries.yaml
    faithfulness.py
  reports/
```

### Data model (SQLite)

* `faculty`: `id, name, area, homepage_url, scholar_url, openalex_author_id, match_status, match_notes, media_json`.
  * `match_status` is one of `confirmed`, `needs_review`, or `not_found`.
  * `media_json` stays empty for now. It is reserved for future professor videos.
* `papers`: `id, openalex_work_id UNIQUE, doi, title, title_normalized, publication_date, year, type, venue, abstract, is_oa, oa_pdf_url, landing_page_url, locations_json, raw_json, fetched_at, updated_at`.
* `paper_authors`: `paper_id, faculty_id, author_position`, with primary key `(paper_id, faculty_id)`.
* `paper_texts`: `paper_id PRIMARY KEY, source, pdf_path, text, n_pages, n_chars, status, error, extracted_at`.
  * `source` is `oa_pdf` or `manual`.
  * `status` is one of `ok`, `no_oa`, `download_failed`, `not_pdf`, `extract_failed`, or `blocked_by_robots`.
* `paper_cards`: `id, paper_id, card_json, basis, model, prompt_version, input_hash, created_at`.
  * `basis` is `full_text` or `abstract_only`.
  * Never update rows in place. Insert a new row, and always read the latest one.
* `prof_profiles`: `id, faculty_id, profile_json, latest_paper_id, based_on_hash, model, prompt_version, created_at`.
* `llm_calls`: `id, purpose, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, batch, cost_usd, created_at`.
* `runs`: `id, step, started_at, finished_at, stats_json`.

Keep `doi`, `title_normalized`, `publication_date`, `type`, and `locations_json` on every paper, even though the MVP doesn't use all of them. A later version will merge the working-paper, conference, and journal versions of the same paper. Do not attempt that merge now.

### CLI

```
python -m pipeline faculty | works | fulltext | cards | profiles | index | refresh | costs
```

`refresh` runs all steps incrementally, in order. Every step prints a short summary and writes a row to `runs`.

### After every part

Print a summary of what was built, the results of the acceptance checks, and anything that needs the user's decision. Then stop and wait.

## Part 1 — Project setup and faculty resolution

Goal: match every professor in `data/faculty.csv` to the right OpenAlex author ID.

The user provides `data/faculty.csv` in this format:

```csv
name,area,homepage_url,scholar_url,openalex_author_id
Jane Doe,Strategy,https://www.isb.edu/...,https://scholar.google.com/citations?user=...,
```

* Only `name` is required.
* `openalex_author_id` (e.g. `A5012345678`) is optional. If the user fills it in, trust it.
* `scholar_url` is for the human reviewer only. Never fetch it.

Steps:

1. Scaffold the project. Create the repo, `requirements.txt`, `.env.example`, `config.py`, the SQLite schema in `db.py` (using `CREATE TABLE IF NOT EXISTS`), and the CLI skeleton.
2. Build a small OpenAlex client.
   * Send the API key with every request. OpenAlex has required keys since February 2026. A free key comes with a small daily usage budget: ID lookups are free, list and filter calls are cheap, and search calls cost more, so prefer filtering by ID.
   * Put `CONTACT_EMAIL` in the User-Agent.
   * Use cursor pagination with `per_page=200`.
   * Retry with exponential backoff on 429 and 5xx responses.
   * During development, cache raw responses to disk so you don't pay twice for the same call.
3. Find ISB's OpenAlex institution ID(s) through the institutions endpoint (search for "Indian School of Business"). Print the candidates with their display names, locations, and works counts. Save the chosen ID(s) in `config.py`. If more than one record looks plausible, ask the user to confirm.
4. Match each faculty row that has no `openalex_author_id`.
   * Search authors by name, restricted to authors with a current or past affiliation to the ISB institution ID.
   * Score each candidate on three things: `rapidfuzz` name similarity, ISB affiliation, and works count.
   * Exactly one strong candidate → set `confirmed`.
   * Several candidates, or only weak ones → set `needs_review` and put the top candidates in `match_notes`.
   * No candidates → set `not_found`.
5. Write `reports/faculty_resolution.csv` for the user to review. Include the name, status, chosen ID, and each candidate's ID, display name, affiliations, works count, and a link to their OpenAlex profile. The user can paste corrected IDs into `faculty.csv` and re-run the step.
6. Write `reports/possibly_missing_faculty.csv`. List ISB-affiliated OpenAlex authors with at least 5 works who are not in `faculty.csv`. This is for the user to review. Never add them automatically, because they may be PhD students, alumni, or co-authors.

Acceptance checks

* [ ] `python -m pipeline faculty` runs end to end and is safe to re-run.
* [ ] It prints counts for confirmed, needs_review, and not_found.
* [ ] IDs the user entered in `faculty.csv` are never overwritten.
* [ ] No request is ever made to Google Scholar.

## Part 2 — Paper metadata ingestion

Goal: store every work by every confirmed professor, with its raw JSON.

Steps:

1. Fetch works. For each confirmed professor, list their works filtered by author ID, using cursor pagination.
   * Keep research outputs: article, preprint, review, book, and book-chapter.
   * Skip paratext, errata, editorials, peer reviews, and datasets.
   * Make the allow-list a config value.
2. Upsert into `papers` by `openalex_work_id` and store the full raw JSON. Rebuild the abstract from OpenAlex's `abstract_inverted_index`: map each word to its positions, sort by position, and join. If there is no abstract, store `null`.
3. Set `oa_pdf_url`. Prefer `best_oa_location.pdf_url`. If that is missing, use any other location's `pdf_url`. Store all locations in `locations_json`.
4. Set `title_normalized`: lowercase, with punctuation and extra whitespace stripped. Store it only; do not merge anything.
5. Link `paper_authors` for every ISB professor on the paper. A paper co-authored by two ISB professors belongs to both.
6. Make runs incremental. Re-fetch works per author and upsert them. Update `updated_at` only when the raw JSON has changed.

Acceptance checks

* [ ] A report shows papers per professor, the percentage with an abstract, and the percentage with an OA PDF URL.
* [ ] For a spot-check on 3 professors, print each one's 5 most recent papers (title, year, venue) so the user can compare them against the professor's homepage.
* [ ] Re-running adds no duplicate rows.

## Part 3 — Full text

Goal: extract text, with page markers, for every paper whose full text is legally available.

Steps:

1. Download open-access PDFs for papers that have an `oa_pdf_url` and no `ok` row in `paper_texts`.
   * Check robots.txt first, using `urllib.robotparser`.
   * Send the identifying User-Agent, use a 30-second timeout, cap files at 50 MB, and make at most 1 request per second to each domain.
   * Accept only responses that really are PDFs, judged by content-type and a `%PDF` header. Mark landing pages and HTML as `not_pdf`.
2. Fall back to other URLs. If the first URL fails, try the other PDF URLs in `locations_json`.
3. Avoid paid downloads. OpenAlex also has a paid PDF-download endpoint. Don't use it by default; only use it when the `--use-openalex-content` flag is passed.
4. Attach manual PDFs. For each row in `data/manual_pdfs.csv` (columns `filename, doi_or_openalex_id`), attach the PDF to the matching paper with `source='manual'`. A manual PDF takes priority over a downloaded one.
5. Extract text with PyMuPDF, inserting `[[page N]]` at the start of each page. Fix hyphenated words split across lines, and remove repeated headers and footers where that is simple and safe. If a multi-page PDF yields fewer than 2,000 characters, it is probably scanned: mark it `extract_failed`.
6. Record the status and any error for every attempt.

Acceptance checks

* [ ] A coverage report shows counts by status and the percentage of papers with full text for each professor.
* [ ] Re-running skips papers that are already `ok`.
* [ ] Opening any `ok` text shows readable prose with page markers.

## Part 4 — Paper cards

Goal: generate one structured, faithful card per paper with Claude.

The card schema below is validated with pydantic:

```json
{
  "one_liner": "the paper's main takeaway in 25 words or fewer",
  "plain_english_summary": "3-5 sentences for a first-year MBA student",
  "research_question": "string",
  "method": "string",
  "data": "sample, setting, time period",
  "key_findings": ["string"],
  "why_it_matters": "implications for managers, policymakers or investors, as stated or directly implied by the paper",
  "topics": ["5-10 short topic tags"],
  "context": {"industries": ["string"], "geographies": ["string"]},
  "basis": "full_text | abstract_only"
}
```

Save this as `prompts/card_v1.md`:

```
You are writing a summary card of one academic paper for MBA students at the Indian School of Business. You will receive the paper's metadata and either its full text or only its abstract.

Rules:
1. Use only the text provided. Do not add facts, numbers, names, or context from outside it.
2. If a field is not stated in the text, write exactly "Not stated in the available text." Never guess.
3. Report findings the way the authors state them, keeping their hedges ("suggests", "is associated with"). Never turn a correlation into a cause, and never make a finding stronger than the paper does.
4. Write for a smart first-year MBA student: plain English, no equations, and a short gloss for any technical term.
5. If you only have the abstract, keep the card short, set basis to "abstract_only", and set method and data to "Not stated in the available text." unless the abstract states them.
6. Topic tags should be the words a student would search with (e.g. "IPO underpricing", "family firms", "platform pricing"), not journal jargon.

Return the card using the provided schema.
```

Steps:

1. Build the input for each paper: title, authors, year, and venue, followed by the full text if available, or otherwise the abstract. Skip papers that have neither, and list them in the report. If the full text is very long, drop the references section only when you can detect it reliably. Never truncate the body of the paper.
2. Get JSON output through the API's structured-output support, or through a single forced tool call whose input schema is the card schema. Validate the result with pydantic, and retry once if it is invalid.
3. Dry run with a model comparison. `python -m pipeline cards --sample 5 --compare` sends the same 5 papers, a mix of full-text and abstract-only, synchronously through both `claude-haiku-4-5-20251001` and `claude-sonnet-5`.
   * Write `reports/card_model_comparison.md` with each paper's two cards side by side, plus the cost of each.
   * Do not save these as current cards.
   * Stop here and wait for the user to confirm `CARD_MODEL` before the full run. Haiku is the default. Switch to Sonnet only if Haiku's cards add facts that aren't in the source, leave out key findings, or break the "Not stated" rule.
4. Do the full run with `CARD_MODEL` through the Message Batches API, which is half price and usually returns results within hours. Before submitting, estimate the cost using token counting, or roughly as chars ÷ 3.5, and require `--yes` to proceed. Poll until the batch completes, write the results, and record usage in `llm_calls`.
5. Skip unchanged papers. Set `input_hash` = hash(input text + prompt_version + model). If a paper's latest card has the same hash, skip it.

Acceptance checks

* [ ] Every paper with a title plus an abstract or full text has exactly one current card.
* [ ] 20 random cards are printed next to their source excerpts for a human spot-check, and none contains facts absent from the source.
* [ ] The cost of the run is printed.

## Part 5 — Professor profiles

Goal: a research profile for each professor, built from their paper cards rather than their full papers.

Profile schema:

```json
{
  "research_summary": "5-7 sentences on what this professor studies and why it matters",
  "core_themes": [{"theme": "string", "description": "string", "paper_ids": [1, 2]}],
  "evolution": "how their focus has shifted over time, or 'Not enough papers to say.'",
  "signature_findings": [{"finding": "string", "paper_id": 3}],
  "good_to_talk_to_about": [{"topic": "string", "paper_id": 4}]
}
```

Save this as `prompts/profile_v1.md`:

```
You are writing a research profile of an Indian School of Business professor for students. You will receive summary cards of the professor's papers, each with a paper_id and year.

Rules:
1. Use only the cards. Every theme, finding, and topic must cite paper_ids from the input.
2. Describe the research, not the person. No praise and no adjectives like "renowned", "leading", or "prolific".
3. Describe how the focus has shifted over time only if the years support it; otherwise write "Not enough papers to say."
4. Signature findings: at most three, chosen for how central they are to the professor's work, stated with the paper's own hedges.
5. "good_to_talk_to_about": 3-6 concrete topics a student could raise in office hours, each tied to one paper.
6. If a card is abstract-only, do not describe that paper's methods in detail.

Return the profile using the provided schema.
```

Steps:

1. Gather each professor's current cards, sorted by publication date with the newest first. For each card, pass `paper_id`, year, title, basis, `one_liner`, `plain_english_summary`, `key_findings`, and `topics`.
2. Handle professors with many papers. If the input would exceed about 60k tokens, pass the newest 40 papers in full and the rest as title plus `one_liner` only.
3. Set `latest_paper_id` to the paper with the most recent `publication_date`. This is a known limitation: it may pick a working-paper version of a later journal article. Do not try to fix that now.
4. Validate citations. Every cited `paper_id` must belong to that professor. Retry once if one doesn't.
5. Skip unchanged professors. Set `based_on_hash` = hash(the professor's paper IDs + their card hashes + prompt_version), and regenerate the profile only when the hash changes.

Acceptance checks

* [ ] There is one current profile for each confirmed professor who has at least 1 card.
* [ ] No profile cites an invalid `paper_id`.
* [ ] 3 profiles are printed for human review.

## Part 6 — Search index

Goal: hybrid search that returns papers and professors in under a second.

Steps:

1. Build one search document per paper from its title, `one_liner`, `plain_english_summary`, `key_findings`, `topics`, and venue.
2. Dense search. Embed the documents with `BAAI/bge-small-en-v1.5` and normalize the vectors. At query time, prefix each query with "Represent this sentence for searching relevant passages: ". Store the vectors in `data/index/embeddings.npy` with a matching `paper_ids.json`, and compute cosine similarity by brute force in numpy.
3. Keyword search. Build a BM25 index over the same documents (simple tokenizer, lowercased, stopwords removed) and pickle it to `data/index/`.
4. Combine the two with reciprocal rank fusion (k = 60) and return the top 20 papers.
5. Rank professors. Take the top 50 papers after fusion. Score each professor by the sum of their best 3 paper scores, so that one lucky paper doesn't dominate and prolific authors don't win on volume alone. Return the top 8 professors, with their matching papers as evidence.
6. Name search. Use `rapidfuzz` over faculty names.
7. Handle weak matches. If the best result after fusion falls below a threshold (tune it on the eval set), show "No strong matches" plus the closest topics.
8. Keep the index incremental. Re-embed only the papers whose current card has changed.

Create `evals/search_queries.yaml` with 20 placeholder entries (`query`, `expected_professors`) for the user to fill in. Add an eval command that reports the top-3 professor hit rate.

Acceptance checks

* [ ] A query takes under 1 second on a laptop once the model is loaded.
* [ ] The eval runs and reports the hit rate. The target is at least 80% once the user has filled in the file.

## Part 7 — Explain-this-paper chat

Goal: a grounded, cited, plain-English conversation about one paper.

Save this as `prompts/chat_system_v1.md`:

```
You help ISB students understand one research paper, which is provided as a document.

1. Ground every factual statement about the paper in the document, using citations.
2. Write in plain English for an MBA student. Define technical terms briefly. Use a concrete example when it helps.
3. When asked to explain the paper, lead with the one-sentence takeaway, then briefly cover the question, how the authors studied it, what they found, and why it matters in practice. Offer to go deeper on any part rather than covering everything at length.
4. If something is not in the paper, say so plainly. You may add general background only when you label it clearly as general context, not from the paper.
5. Never state or guess the authors' personal views, motives, or unpublished work.
6. If you only have the abstract, say that at the start and stay within what the abstract states.
```

Steps:

1. Build the request.
   * Send the paper as a plain-text document content block, with its title set and citations enabled.
   * Put `cache_control` on the document so that follow-up turns read it from the cache.
   * Place the metadata (title, authors, year, venue, basis) in a short text block before the document.
2. Handle abstract-only papers. Send the abstract as the document; the system prompt takes care of the disclaimer. Show a link to the paper's landing page.
3. Render the citations. Parse the response's text blocks and their citations. Map each citation's character range to a page number using the `[[page N]]` markers. Show cited sentences with superscript markers; expanding a marker shows "p. N" and the cited source text.
4. Keep the conversation history in Streamlit session state and send the full history on each turn. Streaming is optional; getting the citations right comes first.
5. Log usage in `llm_calls`, including cache read and write tokens.

Acceptance checks

* [ ] On 3 papers × 5 questions, every factual sentence about the paper has a citation.
* [ ] Asking "What does this paper say about [an unrelated topic]?" gets a plain answer that the paper doesn't cover it.
* [ ] The usage for the second turn shows cache reads for the document.

## Part 8 — Streamlit app

Goal: a clean demo app that runs with one command: `streamlit run app/app.py`.

The app has three views:

1. Search (home).
   * One search box, plus 4–6 preset demo queries as buttons.
   * Results come in two sections:
     * Professors: name, area, top themes, and why they matched (the titles of their matching papers).
     * Papers: title, year, venue, `one_liner`, a "Full text" or "Abstract only" badge, and buttons for "Explain" and "View professor".
2. Professor page.
   * Name, area, and homepage link.
   * Research summary.
   * Core themes, each with its linked papers.
   * Signature findings.
   * "Good to talk to about".
   * The latest paper's card, with an "Explain" button.
   * The full paper list, newest first.
   * An empty, hidden slot for a future video.
3. Paper page.
   * Metadata and a link to the source.
   * The card.
   * The chat from Part 7, with a starter button labelled "Explain this paper".

Design: neutral and readable, with generous whitespace. Do not use ISB logos or brand assets. Put this footer on every page: "Summaries are AI-generated from the papers' text. Check the cited sources."

Acceptance checks

* [ ] The full walk-through works: search → professor → paper → chat → back.
* [ ] The app does not crash on an empty or partial database, and it shows clear empty states.

## Part 9 — Refresh, cost, and faithfulness check

1. `python -m pipeline refresh` runs faculty → works → fulltext → cards (batch) → profiles → index incrementally. Only new or changed items are processed.
2. `python -m pipeline costs` prints total and per-step LLM spend from `llm_calls`.
3. `evals/faithfulness.py` samples N cards that have full text (default 20). For each card, it asks `EVAL_MODEL` (Sonnet by default, so a different, stronger model checks the cards) to list every claim in the card, label each one as supported, unsupported, or not checkable, and quote the supporting source sentence. It writes `reports/faithfulness.md` with the unsupported claims at the top.
4. The README covers setup, the order in which to run the commands, how to add faculty PDFs, how to re-run, and the known limitations: duplicate versions of the same paper, open-access-only full text, and abstract-only cards.

Acceptance checks

* [ ] Running `refresh` a second time, right after the first, makes no LLM calls.
* [ ] The faithfulness report is generated. The user reviews the unsupported claims before any faculty demo.
