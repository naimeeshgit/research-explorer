# Research brief: adding a faculty member

You are adding ISB faculty to the ISB Research Explorer, a website for MBA students. Each
summary is researched and written by hand from public sources. **No LLM APIs, no scripts
that call models.** You read the sources and write the JSON yourself.

Repo: `/home/claude/research-explorer`. Read `CONTENT_GUIDE.md` first (schema + rules).
Example of a paper file: `content/papers/W4389670148.json` (ignore its summary text quality;
follow the schema).

## Steps for each professor

1. **ISB profile.** Fetch (WebFetch) `https://www.isb.edu/faculty-and-research/faculty-directory/<first-last>`.
   If that 404s, WebSearch `"<name>" site:isb.edu`. Record title (e.g. "Assistant Professor,
   Marketing"), area, homepage URL (the ISB profile URL, or a personal site if listed), research
   interests, and the full publication + working-paper list shown.
   Also check a personal website / Google Scholar-style page if one is linked, for working papers.
2. **Publications.** Every journal article, book chapter and working paper on their ISB
   profile/personal site gets a paper file. Skip teaching cases, op-eds, blog posts and HBR-style
   practitioner pieces unless the profile lists nothing else.
3. **Summaries.** Write a `summary` for up to **12** papers per professor: prioritise recent
   (2018+), top-journal and working papers students would find interesting. For each one:
   - Find the abstract: ISB research-directory page for the paper
     (`https://www.isb.edu/faculty-and-research/research-directory/<slug>`), the journal page,
     SSRN, NBER, arXiv, RePEc/IDEAS, or the author's site.
   - If an open PDF exists (author site, arXiv, SSRN mirror, NBER), try WebFetch on it and read
     the intro/conclusion for method, data and findings. If you read the paper itself, basis is
     `full_text`. If abstract plus other pages (journal page, author's description, talks, press
     coverage), basis is `published_sources`. If only the abstract, `abstract_only`.
   - `source`: `{"kind": "claude-research", "createdAt": "2026-10-24", "sources": [every URL you used]}`.
   - Other papers: same file, `"summary": null`, but still fill `abstract` if you found it.
4. **Profile** in the faculty file: `summary` (2–4 sentences, plain English: what they study and
   why it matters), 2–4 `themes` (each with a name, 1–2 sentence description, and the paper IDs
   that belong to it), `talkTo` (3–6 topics a student could bring to office hours), `sources`.

## Writing rules (non-negotiable)

- Only claims supported by sources you actually read. No invented numbers, datasets, years,
  co-authors or findings. If something isn't in the sources, write
  "Not stated in the available sources." for that field.
- Keep the authors' hedges ("suggests", "is associated with"); never upgrade correlation to cause.
- Audience: a sharp first-year MBA student. Plain English, gloss jargon in a few words, no equations.
- `oneLiner`: one sentence, ≤25 words, says the finding, not "this paper studies…".
- `overview`: 3–5 sentences. `findings`: 2–5 bullets. `topics`: 4–8 search-friendly tags
  (lowercase unless a proper noun, e.g. "platform pricing", "India", "retail returns").
- Never copy the abstract verbatim into the summary; paraphrase.

## Files

- Faculty: `content/faculty/<slug>.json`, slug = name lowercased, non-alphanumerics → `-`
  (e.g. `abhinav-uppal`). Keys: slug, name, title, area, homepage, openalex (list of OpenAlex
  author IDs if you find one, else []), photo (null), profile.
- Papers: `content/papers/<id>.json`. `id` = OpenAlex work ID. Look it up with WebFetch on
  `https://api.openalex.org/works/doi:<doi>` (or `https://api.openalex.org/works?search=<title>`)
  and **check the returned title matches**. If there's no match, use `X-<slug>-<year>-<two-words>`
  (e.g. `X-abhinav-uppal-2025-bricks-returns`). Keys exactly as in CONTENT_GUIDE.md: id, title,
  year, date (or null), type ("article" | "preprint" | "book-chapter" | "book"), venue, doi
  (full https://doi.org/... URL or null), url, pdf, citations (from OpenAlex, else 0), authors
  ([{name, isb?}] in paper order; set `"isb": "<slug>"` on the ISB faculty author), isb ([slugs]),
  abstract, summary, versions ([]).
- **Before writing a paper file, check whether it already exists** (another researcher or an
  earlier export may have written it). If it does, don't overwrite: add your slug to `isb` and to
  the matching author's `isb` field, and only add a summary if it has none or an `ai-pipeline` one.
- When done, run `node scripts/check-content.mjs` and fix every error in *your* files.

## Report back (short)

Per professor: title/area, profile URL, number of paper files written, number with summaries
(by basis), any doubts (e.g. name ambiguity, not actually faculty, sources that conflicted).
