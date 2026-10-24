"""Part 4: one structured, faithful summary card per paper.

  python -m pipeline cards --sample 5 --compare   # CARD_MODEL_CANDIDATES on 5 papers, nothing saved
  python -m pipeline cards                        # estimate the full run's cost, then stop
  python -m pipeline cards --yes                  # generate cards one by one (resumable), save
  python -m pipeline cards --review 20            # 20 random cards next to their sources

Cards are append-only: a new row per (paper, input_hash); the latest row is current.
input_hash = sha256(card input text + prompt_version + model), so unchanged papers are
never paid for twice.
"""
import csv
import hashlib
import json
import random
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from rapidfuzz import fuzz

import config
from pipeline import costs, db, llm

NOT_STATED = "Not stated in the available text."


# --- Schema ------------------------------------------------------------------------------

class CardContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    industries: list[str]
    geographies: list[str]


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")
    one_liner: str
    plain_english_summary: str
    research_question: str
    method: str
    data: str
    key_findings: list[str]
    why_it_matters: str
    topics: list[str]
    context: CardContext
    basis: Literal["full_text", "abstract_only"]

    @field_validator("one_liner")
    @classmethod
    def _one_liner_short(cls, v: str) -> str:
        if len(v.split()) > 25:
            raise ValueError(f"one_liner has {len(v.split())} words; the limit is 25")
        return v

    @field_validator("key_findings")
    @classmethod
    def _has_findings(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("key_findings is empty; use [\"Not stated in the available text.\"]")
        return v

    @field_validator("topics")
    @classmethod
    def _topic_count(cls, v: list[str]) -> list[str]:
        # The prompt asks for 5-10; a very short abstract can justify 3.
        if not 3 <= len(v) <= 10:
            raise ValueError(f"topics has {len(v)} tags; expected 5-10")
        return v


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _str_list(desc: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": desc}


CARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["one_liner", "plain_english_summary", "research_question", "method", "data",
                 "key_findings", "why_it_matters", "topics", "context", "basis"],
    "properties": {
        "one_liner": _str("The paper's main takeaway in 25 words or fewer."),
        "plain_english_summary": _str("3-5 sentences for a first-year MBA student."),
        "research_question": _str("The question the paper asks."),
        "method": _str("How the authors studied it."),
        "data": _str("Sample, setting, time period."),
        "key_findings": _str_list("The main findings, with the authors' own hedges."),
        "why_it_matters": _str("Implications for managers, policymakers or investors, as stated "
                               "or directly implied by the paper."),
        "topics": _str_list("5-10 short topic tags a student would search with."),
        "context": {
            "type": "object",
            "additionalProperties": False,
            "required": ["industries", "geographies"],
            "properties": {"industries": _str_list("Industries studied."),
                           "geographies": _str_list("Countries or regions studied.")},
        },
        "basis": {"type": "string", "enum": ["full_text", "abstract_only"],
                  "description": "full_text if the paper text was provided, abstract_only otherwise."},
    },
}
OUTPUT_CONFIG = {"format": {"type": "json_schema", "schema": CARD_SCHEMA}}


def system_prompt() -> str:
    return (config.PROMPTS_DIR / f"{config.CARD_PROMPT_VERSION}.md").read_text().strip()


# --- Input building -------------------------------------------------------------------------

REF_HEADING = re.compile(r"\s*(?:\d+\.?\s*)?(references|bibliography|works cited|literature cited|"
                         r"reference list)\s*:?\s*", re.I)
# Anything after the references that must be kept: appendices, and tables/figures that
# journals print after the reference list.
AFTER_REFS_HEADING = re.compile(r"\s*((?:online\s+)?(appendix|appendices|supplementary (material|appendix))\b.{0,60}"
                                r"|(table|figure|exhibit|fig\.)\s+[A-Z]?\d+.{0,70})", re.I)
PAGE_MARKER = re.compile(r"\[\[page \d+\]\]")
YEAR = re.compile(r"\b(19[5-9]\d|20[0-3]\d)[a-z]?\b")


def strip_references(text: str) -> tuple[str, bool]:
    """Drop the reference list only when it is detected reliably: a standalone heading in the
    back 60% of the text, followed by text dense with publication years (at least one per
    400 characters, as in a citation list). The list ends at the first appendix, table or
    figure heading; those and all [[page N]] markers are kept. Nothing else is removed."""
    lines = text.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    heads = [i for i, l in enumerate(lines)
             if REF_HEADING.fullmatch(l) and offsets[i] > 0.4 * len(text)]
    if not heads:
        return text, False
    start = heads[-1]
    end = next((j for j in range(start + 1, len(lines))
                if len(lines[j]) < 90 and AFTER_REFS_HEADING.fullmatch(lines[j])), len(lines))
    body = "\n".join(l for l in lines[start + 1:end] if not PAGE_MARKER.fullmatch(l.strip()))
    n_years = len(YEAR.findall(body))
    if n_years < 5 or n_years < len(body) / 400:
        return text, False
    kept = lines[:start] + [l for l in lines[start:end] if PAGE_MARKER.fullmatch(l.strip())] + lines[end:]
    return "\n".join(kept), True


def paper_authors(raw_json: str) -> str:
    work = json.loads(raw_json)
    names = [(a.get("author") or {}).get("display_name") or a.get("raw_author_name")
             for a in work.get("authorships") or []]
    names = [n for n in names if n]
    return ", ".join(names[:12]) + (f", and {len(names) - 12} others" if len(names) > 12 else "")


ELIGIBLE_SQL = """
    SELECT p.id, p.openalex_work_id, p.title, p.year, p.venue, p.abstract, p.raw_json,
           p.landing_page_url, t.status AS text_status, t.text AS full_text
    FROM papers p
    LEFT JOIN paper_texts t ON t.paper_id = p.id
    WHERE p.id IN (SELECT paper_id FROM paper_authors)
"""


def build_input(paper) -> dict:
    """Returns {basis, user_text, source_text, refs_stripped} or {skip: reason}."""
    if not (paper["title"] or "").strip():
        return {"skip": "no title"}
    if paper["text_status"] == "ok" and paper["full_text"]:
        basis = "full_text"
        source, refs_stripped = strip_references(paper["full_text"])
    elif paper["abstract"]:
        basis, source, refs_stripped = "abstract_only", paper["abstract"], False
    else:
        return {"skip": "no full text and no abstract"}
    header = (f"Title: {paper['title']}\n"
              f"Authors: {paper_authors(paper['raw_json'])}\n"
              f"Year: {paper['year'] or 'unknown'}\n"
              f"Venue: {paper['venue'] or 'unknown'}\n"
              f"Available text: {'full text' if basis == 'full_text' else 'abstract only'}\n")
    tag = "paper_text" if basis == "full_text" else "abstract"
    user_text = f"{header}\n<{tag}>\n{source}\n</{tag}>"
    return {"basis": basis, "user_text": user_text, "source_text": source, "refs_stripped": refs_stripped}


def input_hash(user_text: str, model: str) -> str:
    return hashlib.sha256(f"{user_text}\n{config.CARD_PROMPT_VERSION}\n{model}".encode()).hexdigest()


def est_tokens(text: str) -> int:
    return int(len(text) / config.CHARS_PER_TOKEN)


# --- API calls ------------------------------------------------------------------------------

def parse_card(result: "llm.LLMResult", basis: str) -> tuple[Card | None, str | None]:
    if not result.ok:
        return None, f"stop_reason={result.stop_reason}"
    try:
        card = Card.model_validate(json.loads(result.text))
    except (json.JSONDecodeError, ValidationError) as e:
        return None, f"invalid card: {str(e)[:500]}"
    if card.basis != basis:
        card.basis = basis  # the basis is a fact about our input, not the model's call
    return card, None


def generate_sync(conn, model: str, inp: dict, purpose: str) -> tuple[Card | None, str | None, float]:
    """One call plus one retry if the card is invalid. Returns (card, error, cost_usd)."""
    total, err = 0.0, None
    for _ in range(2):
        try:
            res = llm.generate_json(model, system_prompt(), inp["user_text"], CARD_SCHEMA,
                                    config.CARD_MAX_TOKENS, config.THINKING_LEVEL.get(model))
        except llm.LLMError as e:
            return None, str(e), total
        total += costs.log_usage(conn, purpose, model, res.usage)
        card, err = parse_card(res, inp["basis"])
        if card:
            return card, None, total
    return None, err, total


def save_card(conn, paper_id: int, card: Card, model: str, ihash: str) -> None:
    conn.execute(
        """INSERT INTO paper_cards (paper_id, card_json, basis, model, prompt_version, input_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, card.model_dump_json(), card.basis, model, config.CARD_PROMPT_VERSION, ihash, db.now()),
    )
    conn.commit()


def latest_hashes(conn) -> dict[int, str]:
    return {r["paper_id"]: r["input_hash"] for r in conn.execute(
        "SELECT paper_id, input_hash FROM paper_cards WHERE id IN "
        "(SELECT MAX(id) FROM paper_cards GROUP BY paper_id)")}


# --- Faithfulness helpers (heuristics for human review, not a verdict) ------------------------

NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")


def numbers_not_in_source(card: Card, source: str) -> list[str]:
    """Numbers in the card that never appear in the source text. A cheap flag for invented figures."""
    src = source.replace(",", "")
    text = " ".join([card.one_liner, card.plain_english_summary, card.research_question, card.method,
                     card.data, card.why_it_matters, *card.key_findings])
    missing = []
    for n in NUM.findall(text):
        bare = n.replace(",", "").rstrip("%")
        if bare and bare not in src and n not in missing:
            missing.append(n)
    return missing


def not_stated_fields(card: Card) -> list[str]:
    fields = ["research_question", "method", "data", "why_it_matters"]
    return [f for f in fields if getattr(card, f).strip() == NOT_STATED]


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def best_source_sentence(claim: str, source: str) -> tuple[str, float]:
    sents = [s.strip() for s in SENT_SPLIT.split(PAGE_MARKER.sub(" ", source).replace("\n", " ")) if len(s.strip()) > 20]
    if not sents:
        return "", 0.0
    best = max(sents, key=lambda s: fuzz.token_set_ratio(claim, s))
    return best, fuzz.token_set_ratio(claim, best)


# --- Model comparison (dry run) ---------------------------------------------------------------

def compare(n: int = 5, seed: int | None = None) -> None:
    conn = db.connect()
    for m in config.CARD_MODEL_CANDIDATES:
        llm.check_key(m)
    rng = random.Random(seed)
    papers = conn.execute(ELIGIBLE_SQL).fetchall()
    built = [(p, build_input(p)) for p in papers]
    full = [(p, i) for p, i in built if i.get("basis") == "full_text"
            and all(est_tokens(i["user_text"]) < config.MODEL_INPUT_LIMIT[m] for m in config.CARD_MODEL_CANDIDATES)]
    abst = [(p, i) for p, i in built if i.get("basis") == "abstract_only"]
    n_full = min(len(full), max(n - min(len(abst), n // 2), 0))
    sample = rng.sample(full, n_full) + rng.sample(abst, min(len(abst), n - n_full))
    if not sample:
        print("No papers with full text or an abstract. Run works and fulltext first.")
        return

    models = config.CARD_MODEL_CANDIDATES
    per_model_cost = Counter()
    sections = []
    with db.run(conn, "cards_compare") as stats:
        for k, (p, inp) in enumerate(sample, start=1):
            print(f"[{k}/{len(sample)}] {inp['basis']:<13} {p['title'][:70]}")
            results = {}
            for m in models:
                card, err, cost = generate_sync(conn, m, inp, "card_compare")
                per_model_cost[m] += cost
                results[m] = (card, err, cost)
                print(f"    {m:<28} {'ok' if card else 'FAILED: ' + str(err)[:80]}  ${cost:.4f}")
            sections.append(_compare_section(k, p, inp, results, models))
        stats.update(papers=len(sample), cost_by_model={m: round(c, 4) for m, c in per_model_cost.items()})

    head = [
        "# Card model comparison",
        "",
        f"Prompt: `{config.CARD_PROMPT_VERSION}`. {len(sample)} papers "
        f"({sum(1 for _, i in sample if i['basis'] == 'full_text')} full text, "
        f"{sum(1 for _, i in sample if i['basis'] == 'abstract_only')} abstract only), sent synchronously "
        "to both models. None of these cards were saved.",
        "",
        f"Choose {models[-1]} only if {models[0]}'s cards add facts that aren't in the source, leave out key "
        "findings, or break the \"Not stated\" rule. The automatic flags below are hints for your reading, not verdicts.",
        "",
        "| Model | Total cost (these papers, paid-tier price) | Avg per card |",
        "|---|---|---|",
    ]
    for m in models:
        head.append(f"| `{m}` | ${per_model_cost[m]:.4f} | ${per_model_cost[m] / len(sample):.4f} |")
    out = config.REPORTS_DIR / "card_model_comparison.md"
    config.REPORTS_DIR.mkdir(exist_ok=True)
    out.write_text("\n".join(head) + "\n\n" + "\n\n".join(sections) + "\n")
    print(f"\nCost: " + ", ".join(f"{m} ${c:.4f}" for m, c in per_model_cost.items()))
    print(f"Report: {out.relative_to(config.ROOT)}")
    print(f"CARD_MODEL is currently {config.CARD_MODEL}. Read the report, then confirm or change it in config.py.")


def _cell(value) -> str:
    if isinstance(value, list):
        value = "<br>".join(f"• {v}" for v in value) if value else "(none)"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _compare_section(k, paper, inp, results, models) -> str:
    lines = [f"## {k}. {paper['title']}",
             "",
             f"{paper['year'] or ''} · {paper['venue'] or 'unknown venue'} · **{inp['basis']}**"
             f"{' · references stripped' if inp['refs_stripped'] else ''} · "
             f"~{est_tokens(inp['user_text']):,} input tokens · "
             f"[{paper['openalex_work_id']}](https://openalex.org/{paper['openalex_work_id']})",
             ""]
    if inp["basis"] == "abstract_only":
        lines += ["<details><summary>Source abstract</summary>", "", inp["source_text"], "", "</details>", ""]
    lines += ["| Field | " + " | ".join(f"`{m}`" for m in models) + " |",
              "|---|" + "---|" * len(models)]
    fields = ["one_liner", "plain_english_summary", "research_question", "method", "data", "key_findings",
              "why_it_matters", "topics"]
    cards = {m: results[m][0] for m in models}
    for f in fields:
        lines.append(f"| {f} | " + " | ".join(_cell(getattr(cards[m], f)) if cards[m] else "—" for m in models) + " |")
    lines.append("| industries / geographies | " + " | ".join(
        _cell(cards[m].context.industries + ["—"] + cards[m].context.geographies) if cards[m] else "—" for m in models) + " |")
    lines.append("| ⚑ numbers not found in source | " + " | ".join(
        _cell(numbers_not_in_source(cards[m], inp["source_text"]) or "none") if cards[m] else "—" for m in models) + " |")
    lines.append("| ⚑ \"Not stated\" fields | " + " | ".join(
        _cell(not_stated_fields(cards[m]) or "none") if cards[m] else "—" for m in models) + " |")
    lines.append("| cost | " + " | ".join(f"${results[m][2]:.4f}" for m in models) + " |")
    errs = [f"`{m}` failed: {results[m][1]}" for m in models if not results[m][0]]
    return "\n".join(lines + ([""] + errs if errs else []))


# --- Full run (synchronous, resumable) ------------------------------------------------------------

def plan(conn, model: str) -> tuple[list, Counter, list]:
    """Returns (todo [(paper, inp, hash)], counts, skipped [(paper, reason)])."""
    current = latest_hashes(conn)
    limit = config.MODEL_INPUT_LIMIT.get(model, 180_000)
    todo, skipped, c = [], [], Counter()
    for p in conn.execute(ELIGIBLE_SQL).fetchall():
        inp = build_input(p)
        if "skip" in inp:
            skipped.append((p, inp["skip"]))
            c["skipped"] += 1
            continue
        if est_tokens(inp["user_text"]) > limit:
            skipped.append((p, f"too long for {model} (~{est_tokens(inp['user_text']):,} tokens); not truncated"))
            c["too_long"] += 1
            continue
        h = input_hash(inp["user_text"], model)
        if current.get(p["id"]) == h:
            c["unchanged"] += 1
        else:
            todo.append((p, inp, h))
            c[inp["basis"]] += 1
    return todo, c, skipped


def run(yes: bool = False, count_tokens: bool = False, limit: int | None = None) -> None:
    conn = db.connect()
    model = config.CARD_MODEL
    started = conn.execute("SELECT COALESCE(MAX(id), 0) FROM llm_calls").fetchone()[0]

    with db.run(conn, "cards") as stats:
        todo, c, skipped = plan(conn, model)
        n_all = len(todo)
        if limit:
            todo = todo[:limit]
        write_skipped(skipped)
        print(f"Model {model}, prompt {config.CARD_PROMPT_VERSION}")
        print(f"Cards to generate: {n_all}  (full text {c['full_text']}, abstract only {c['abstract_only']})"
              f"{f', this run limited to {len(todo)}' if len(todo) < n_all else ''}  |  "
              f"unchanged: {c['unchanged']}  |  skipped: {c['skipped'] + c['too_long']} (see reports/cards_skipped.csv)")
        stats.update(model=model, planned=len(todo), **c)
        if not todo:
            report(conn, started)
            return

        n_in = sum(est_tokens(system_prompt() + i["user_text"]) for _, i, _ in todo)
        n_out = len(todo) * config.CARD_EST_OUTPUT_TOKENS
        est = costs.compute_cost(model, n_in, n_out)
        gap = config.LLM_MIN_SECONDS_BETWEEN_CALLS.get(model, 0)
        free = " On the Gemini free tier: $0." if llm.provider_for(model) == "gemini" else ""
        print(f"Estimated cost at paid-tier prices: ${est:.2f}  (~{n_in:,} input tokens by chars ÷ "
              f"{config.CHARS_PER_TOKEN}, ~{n_out:,} output tokens; thinking tokens come on top).{free}")
        if gap:
            print(f"Estimated time: at least {len(todo) * gap / 60:.0f} min ({gap}s between calls, "
                  "LLM_MIN_SECONDS_BETWEEN_CALLS).")
        stats["estimated_usd"] = round(est, 4)
        if not yes:
            print("Nothing sent. Re-run with --yes to generate the cards.")
            return

        llm.check_key(model)
        done = failed = 0
        try:
            for k, (p, inp, h) in enumerate(todo, start=1):
                card, err, cost = generate_sync(conn, model, inp, "card")
                if card:
                    save_card(conn, p["id"], card, model, h)
                    done += 1
                else:
                    failed += 1
                print(f"  [{k}/{len(todo)}] {'ok    ' if card else 'FAILED'} {inp['basis']:<13} "
                      f"{(p['title'] or '')[:60]}{'' if card else '  -> ' + str(err)[:120]}")
        except KeyboardInterrupt:
            print("\nStopped. Cards saved so far are kept; re-run to continue.")
        stats.update(saved=done, failed=failed)
        if failed:
            print(f"{failed} papers failed; they are retried on the next run.")
        report(conn, started)


def write_skipped(skipped) -> None:
    config.REPORTS_DIR.mkdir(exist_ok=True)
    with open(config.REPORTS_DIR / "cards_skipped.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paper_id", "openalex_work_id", "year", "title", "reason", "landing_page_url"])
        for p, reason in skipped:
            w.writerow([p["id"], p["openalex_work_id"], p["year"], p["title"], reason, p["landing_page_url"]])


def report(conn, since_call_id: int | None = None) -> None:
    model = config.CARD_MODEL
    todo, c, skipped = plan(conn, model)
    eligible = c["unchanged"] + len(todo)
    dup = conn.execute("SELECT COUNT(*) FROM (SELECT paper_id FROM paper_cards GROUP BY paper_id)").fetchone()[0]
    print(f"\nCurrent cards: {c['unchanged']} of {eligible} eligible papers are up to date with {model}"
          f" ({len(todo)} still to do). Papers with any card: {dup}.")
    print(f"Skipped (no title, or neither full text nor abstract, or too long): {len(skipped)}")
    if since_call_id is not None:
        spent = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE id > ? "
                             "AND purpose LIKE 'card%'", (since_call_id,)).fetchone()[0]
        print(f"Cost of this run: ${spent:.4f}")


# --- Human spot-check ---------------------------------------------------------------------------

def review(n: int = 20, seed: int | None = None) -> None:
    conn = db.connect()
    rows = conn.execute(f"""
        SELECT c.*, p.title, p.year, p.openalex_work_id FROM paper_cards c JOIN papers p ON p.id = c.paper_id
        WHERE c.id IN (SELECT MAX(id) FROM paper_cards GROUP BY paper_id)""").fetchall()
    if not rows:
        print("No cards yet.")
        return
    rows = random.Random(seed).sample(rows, min(n, len(rows)))
    out = ["# Card spot-check", "",
           f"{len(rows)} random current cards. Each key finding is shown with the closest-matching source "
           "sentence (fuzzy match, for orientation only). ⚑ marks numbers that don't appear in the source. "
           "Check that nothing in a card is absent from the source.", ""]
    flagged = 0
    for r in rows:
        card = Card.model_validate_json(r["card_json"])
        p = conn.execute(ELIGIBLE_SQL + " AND p.id = ?", (r["paper_id"],)).fetchone()
        inp = build_input(p)
        source = inp.get("source_text", "")
        nums = numbers_not_in_source(card, source)
        flagged += bool(nums)
        out += [f"## {r['title']} ({r['year']})", "",
                f"`{r['openalex_work_id']}` · basis **{r['basis']}** · {r['model']} · {r['prompt_version']}", "",
                f"**One-liner:** {card.one_liner}", "", f"**Summary:** {card.plain_english_summary}", "",
                f"**Question:** {card.research_question}  ", f"**Method:** {card.method}  ",
                f"**Data:** {card.data}  ", f"**Why it matters:** {card.why_it_matters}  ",
                f"**Topics:** {', '.join(card.topics)}", "", "**Key findings vs. source:**", ""]
        for kf in card.key_findings:
            sent, score = best_source_sentence(kf, source)
            out += [f"- **Card:** {kf}", f"  - *Source ({score:.0f}%):* {sent[:500]}"]
        out += ["", f"⚑ Numbers not found in source: {', '.join(nums)}" if nums else "No unmatched numbers.", ""]
        if card.basis == "abstract_only":
            out += ["<details><summary>Full abstract</summary>", "", source, "", "</details>", ""]
        print(f"\n=== {r['title'][:90]} ({r['year']}) [{r['basis']}]")
        print(f"  one-liner: {card.one_liner}")
        for kf in card.key_findings[:4]:
            sent, score = best_source_sentence(kf, source)
            print(f"  - {kf[:150]}\n      source ({score:.0f}%): {sent[:200]}")
        if nums:
            print(f"  ⚑ numbers not in source: {', '.join(nums)}")
    path = config.REPORTS_DIR / "card_spotcheck.md"
    path.write_text("\n".join(out) + "\n")
    print(f"\n{len(rows)} cards printed, {flagged} with numbers not found in the source. Full view: {path.relative_to(config.ROOT)}")
