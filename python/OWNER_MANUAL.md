# Owner manual

This file lists what **you** need to do: the steps only you can take and the decisions only
you can make. `README.md` explains how the tool works.

Always run commands from the project folder. Open a terminal and start with:

```bash
cd /Users/naimeeshtiwari/Desktop/ISB-KMP-Archive/isb-research-explorer-gemini
```

(If you see `no such file or directory: .venv/bin/python`, you skipped this `cd`.)

---

## 1. One-time setup

- [x] **Gemini API key.** Get one free at aistudio.google.com/apikey.
- [x] **OpenAlex API key.** Get one free at openalex.org/settings/api.
- [x] **`.env` file** with `GEMINI_API_KEY`, `OPENALEX_API_KEY`, `CONTACT_EMAIL`.
  - `CONTACT_EMAIL` doesn't have to be your OpenAlex login email. Any address you check will do.
  - It's sent in the User-Agent on every request to OpenAlex and to the sites PDFs are
    downloaded from, so their admins can contact you instead of blocking the tool. It
    appears in their server logs. It is **not** sent to Gemini.
- [x] **Fix Gemini billing.** Done 2026-09-29: `.env` now has a free-tier key (a project
  with no billing). Both models answer.
  - The same evening the key hit the free tier's daily cap (HTTP 429), then started
    returning `402 prepayment credits are depleted`, so billing seems to have been switched
    on for that project.
- [ ] **Anthropic API key (cards now use Claude Haiku 5.5, as of 2026-10-20).** Get a key
  at console.anthropic.com → API Keys, put it in `.env` as `ANTHROPIC_API_KEY=sk-ant-...`,
  and keep the other lines. The `anthropic` package is already installed in `.venv`.
  Anthropic does not train on API data by default, so private PDFs are fine here.
- [ ] **Before sending private PDFs to Gemini, move to a paid key.** This applies only if you
  switch any `*_MODEL` back to `gemini-*`. On the free tier, calls cost $0
  but Google may use what you send to improve its products. That's fine for open-access
  papers. Turn on billing in AI Studio before processing any PDF a professor sends you
  privately. If you go paid, set `LLM_MIN_SECONDS_BETWEEN_CALLS` in `config.py` to `0` to
  run faster.
  - On the free tier, `gemini-3.8-flash` often answers "overloaded" (HTTP 503). In the
    2026-09-29 comparison it failed on 2 of 5 papers, even with retries. Flash-Lite had no
    trouble.

## 2. Faculty list: `data/faculty.csv`

Current list: Bhagwan Chowdhry, Deepa Mani, Madhu Viswanathan, Prasanna Tantri,
Ramabhadran Thirumalai, Sarang Deo.

- [ ] **Add the rest of the faculty** (only `name` is required), then run:
  ```bash
  .venv/bin/python -m pipeline faculty
  ```
- [ ] **Resolve `needs_review` rows** in `reports/faculty_resolution.csv`. Pick the right
  profile, paste its ID into the last column of `faculty.csv`, and re-run. If one person has
  two profiles, enter both as `A123|A456`. Check the papers first, because two profiles with
  the same name can be two different people (see Madhu below).
- [ ] **Skim `reports/possibly_missing_faculty.csv`** for ISB faculty you forgot. It also
  lists alumni and PhD students, so add people by hand; nothing is added automatically.
- [ ] **Fill in `area` and `homepage_url`** for each professor. I guessed the areas
  (Thirumalai as Finance). Homepage links will appear in the app.

Open questions about the current 6:

- [ ] **Madhu Viswanathan.** Only 17 papers are linked, which seems low. Compare with his
  homepage:
  ```bash
  .venv/bin/python -m pipeline works --report-only --spot-check "Madhu Viswanathan"
  ```
  His 2015 consumer-psychology handbook chapter may belong to the *other* Madhu Viswanathan
  (`A5009850369`, subsistence-marketplaces research), whom I deliberately left out.
- [ ] **Deepa Mani** may have a second, smaller OpenAlex profile (`A5063796999`, 25 works,
  ISB 2016). If those papers are hers, change her ID to `A5016201625|A5063796999`.

## 3. Refresh the data

Run these in order:

```bash
.venv/bin/python -m pipeline works
.venv/bin/python -m pipeline fulltext
```

- [ ] **Spot-check papers.** `works` prints the 5 most recent papers for 3 random
  professors. Compare them with their homepages.
- [ ] **Decide about conference papers.** They are skipped at the moment, along with
  `report` and `dissertation`. For IS and Operations faculty, conference papers can matter.
  To include them, add `"conference-paper"` to `WORK_TYPES_ALLOWED` in `config.py`.

### What the `fulltext` statuses mean

They are not errors. Each line is one paper:

| Status | Meaning |
|---|---|
| `ok` | PDF downloaded and its text extracted |
| `no_oa` | No free PDF exists as far as OpenAlex knows |
| `blocked_by_robots` | A free PDF exists, but the site forbids bots (e.g. escholarship.org, old UCLA pages) |
| `download_failed` | The site refused: SSRN (403), ISB eprints (login), some publishers |
| `not_pdf` | The link led to a web page, not a PDF |

Expect only about 10% of papers with full text. Everything else gets an "abstract only"
card, and papers with neither get no card.

## 4. Get more full text (biggest quality lever)

- [ ] **Ask the professors for PDFs of their key papers.** This gives the best coverage for
  the faculty demo.
- [ ] **Download blocked PDFs by hand.** A person downloading in a browser is fine;
  robots.txt only applies to bots. To list them:
  ```bash
  sqlite3 data/explorer.db "select p.openalex_work_id, p.title, t.error from paper_texts t join papers p on p.id=t.paper_id where t.status in ('blocked_by_robots','download_failed')"
  ```
- [ ] **Add each PDF:**
  1. Save it into `data/manual_pdfs/`.
  2. Add a line to `data/manual_pdfs.csv`, as `filename,doi_or_openalex_id`, for example:
     ```
     chowdhry_swaps.pdf,W3122843100
     tantri_zombie.pdf,10.1017/S0022109024000000
     ```
  3. Re-run `.venv/bin/python -m pipeline fulltext`. It only processes the new files.
- [ ] **Ask ISB IT about eprints.exchange.isb.edu.** It needs a login, so the tool can't
  fetch ISB's own repository copies. Anonymous read access would help a lot.
- [ ] **Optional: paid OpenAlex PDFs** ($0.01 each). Run
  `.venv/bin/python -m pipeline fulltext --use-openalex-content` to see how many are
  available, then add `--yes` to buy them.

## 5. Paper cards

- [x] **Run the model comparison** (2026-09-29). The result is in `reports/card_model_comparison.md`.
- [x] **Choose `CARD_MODEL`.** Kept `gemini-3.1-flash-lite` for now. It invented no
  numbers and followed the "Not stated" rule. `gemini-3.8-flash` wrote richer cards, with
  confidence intervals and the patient cascade, and it was clearer that one trial's
  primary outcome was not significant. But it failed on 2 of 5 papers (server overloaded).
  Flash-Lite's weak spots:
  - It is terser and leaves out confidence intervals.
  - On one abstract (paper 5, "Slow First, Fast Later") it wrote "Not stated" for method
    and data, even though the abstract describes both.
- [ ] **Decide whether to upgrade the 42 full-text cards to `gemini-3.8-flash`.** That's
  where the quality gap is largest. It costs $0 on the free tier; the risk is 503 retries.
  Switching `CARD_MODEL` regenerates every card, so tell me if you want only the
  full-text ones.
- [x] **See the cost estimate:** 177 cards, $0.57 at paid-tier prices, $0 on the free tier.
- [x] **First full run with `card_v1`** (2026-09-29): 176 of 177 cards. The spot-check
  found that 87 of 135 abstract-only cards said "Not stated" for method, and 91 for data,
  often when the abstract clearly names them. The fix is the new prompt
  `prompts/card_v2.md` (`CARD_PROMPT_VERSION` in `config.py`). It was tested on 8
  affected abstracts and now fills in method and data correctly, while theory papers still
  get "Not stated" for data. The v1 cards stay in the database, but only the newest card
  per paper is shown.
- [x] **Partial regeneration with `card_v2` on Gemini** (2026-09-29): 95 of 177 papers
  were done when the Gemini key stopped working.
- [x] **Choose a Claude model for cards** (2026-10-20): `claude-haiku-5-5`, estimated at
  about $0.21 plus thinking tokens for all 177 cards.
- [x] **Anthropic key added and tested** (2026-10-24). On a test run, Haiku 5.5 wrote
  one-liners over the 25-word limit, so `prompts/card_v3.md` now states the limit. With
  it, 7 of 8 test cards passed.
- [ ] **Regenerate all cards with Haiku 5.5 + `card_v3`** (started 2026-10-24; log in
  `reports/cards_run_haiku.log`). Changing the model regenerates every card, so the set stays consistent:
  ```bash
  .venv/bin/python -m pipeline cards --yes
  ```
  Ctrl-C is safe; re-run to continue. Afterwards, re-check the "Not stated" counts and do
  the spot-check below.
- [ ] **`EVAL_MODEL` is still `gemini-3.8-flash`.** It must differ from `CARD_MODEL`. Pick a
  Claude model for it (and for `PROFILE_MODEL` / `CHAT_MODEL`) before Parts 5, 7 and 9.
- [ ] **Spot-check 20 cards** before any faculty sees them:
  ```bash
  .venv/bin/python -m pipeline cards --review 20
  ```
  Read `reports/card_spotcheck.md`, starting with the ⚑ flags.
- [ ] **Decide the topic count.** Cards currently accept 3–10 topics, although the prompt
  asks for 5–10, because very short abstracts can't support 5. Tell me if you want exactly
  5–10.

## 6. Keep an eye on spend

```bash
.venv/bin/python -m pipeline costs
```

This shows what the calls would cost at paid prices, even on the free tier.

## 7. Next build steps (ask me)

- [ ] Part 5: professor profiles
- [ ] Part 6: search
- [ ] Part 7: explain-this-paper chat
- [x] Part 8, early version (2026-10-24): a blue-and-white Streamlit app with search, professor
  pages and paper pages. It runs on what exists today. Search is keyword-only until Part 6.
  The professor "Research summary" waits for Part 5, and the chat waits for Part 7. Open it with:
  ```bash
  cd /Users/naimeeshtiwari/Desktop/ISB-KMP-Archive/isb-research-explorer-gemini
  .venv/bin/python -m streamlit run app/app.py
  ```
  Then go to http://localhost:8501. Press Ctrl-C in the terminal to stop it.
- [ ] Part 9: one-command refresh and the faithfulness report. Review the unsupported claims
  it lists **before any faculty demo**.
