# Content guide

Everything the site shows lives in `content/`. Edit a file, run `npm run check`, push.

## Faculty: `content/faculty/<slug>.json`

```json
{
  "slug": "prasanna-tantri",
  "name": "Prasanna Tantri",
  "title": "Associate Professor of Finance",
  "area": "Finance",
  "homepage": "https://www.isb.edu/...",
  "openalex": ["A5046112048"],
  "photo": null,
  "profile": {
    "summary": "2–4 sentence plain-English overview of their research.",
    "themes": [
      { "name": "Bank stress and zombie lending", "description": "One or two sentences.", "papers": ["W4389670148"] }
    ],
    "talkTo": ["Indian banking regulation", "Loan officer incentives"],
    "sources": ["https://..."],
    "createdAt": "2026-10-24"
  }
}
```

`slug` must match the file name. `profile` can be `null` until written.

## Papers: `content/papers/<id>.json`

`id` is the OpenAlex work ID (`W…`), and must match the file name. For a paper OpenAlex
doesn't have, use any unique ID starting with `X` (e.g. `X-tantri-2026-pca`).

Key fields: `title`, `year`, `venue`, `doi`, `url`, `pdf`, `authors` (`{"name", "isb"?}` —
set `isb` to the faculty slug to link them), `isb` (list of faculty slugs), `abstract`,
`summary`, `versions`. Set `"hidden": true` to drop a paper from the site without deleting it.

### Summary

```json
"summary": {
  "oneLiner": "One sentence, 25 words max.",
  "overview": "A paragraph a first-year MBA student can follow.",
  "question": "The research question.",
  "method": "How they answered it, in plain words.",
  "data": "What data, from where, which years.",
  "findings": ["Finding, with the authors' own hedges.", "..."],
  "whyItMatters": "For managers, policy, or students.",
  "topics": ["search-friendly tags", "e.g. zombie lending"],
  "industries": ["Banking"],
  "geographies": ["India"],
  "basis": "full_text | abstract_only | published_sources",
  "source": { "kind": "claude-research", "createdAt": "2026-10-24", "sources": ["https://..."] }
}
```

Rules for every summary:

1. Use only what the paper and cited sources say. No outside numbers or names.
2. Keep the authors' hedges ("suggests", "is associated with"). Never turn correlation into cause.
3. If a field isn't covered, write "Not stated in the available sources." Don't guess.
4. `basis`: `full_text` if written from the full paper, `abstract_only` if only the abstract,
   `published_sources` if from the abstract plus the journal page, author site, SSRN, talks or press.
5. List every URL used in `source.sources`.

Summaries with `source.kind: "ai-pipeline"` are the old API-generated drafts and are labelled
as such on the site. They get replaced as hand-researched summaries are written.
