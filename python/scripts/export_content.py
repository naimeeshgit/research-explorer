"""Export the pipeline's SQLite database to the website's JSON content files.

    python3 python/scripts/export_content.py            # from the repo root
    python3 python/scripts/export_content.py --force    # also overwrite hand-edited files

Writes:
  content/faculty/<slug>.json   one per professor (profile; papers are linked by slug)
  content/papers/<W-id>.json    one per paper, with journal/SSRN/working-paper versions merged

The JSON files are the website's source of truth. Summaries written by hand (source.kind
"claude-research") and any file with "locked": true are never overwritten, even with --force.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "python" / "data" / "explorer.db"
OUT = ROOT / "content"

TYPE_RANK = {"article": 0, "book": 1, "book-chapter": 2, "review": 3, "preprint": 4}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def norm_title(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (t or "").lower()))


def authors_of(work: dict, isb_ids: dict) -> list[dict]:
    out = []
    for a in work.get("authorships") or []:
        au = a.get("author") or {}
        name = au.get("display_name") or a.get("raw_author_name")
        if not name:
            continue
        aid = (au.get("id") or "").rsplit("/", 1)[-1]
        entry = {"name": name}
        if aid in isb_ids:
            entry["isb"] = isb_ids[aid]
        out.append(entry)
    return out


def card_to_summary(card: dict, row) -> dict:
    ctx = card.get("context") or {}
    clean = lambda xs: [x for x in (xs or []) if x and "not stated" not in x.lower()]
    return {
        "oneLiner": card.get("one_liner", ""),
        "overview": card.get("plain_english_summary", ""),
        "question": card.get("research_question", ""),
        "method": card.get("method", ""),
        "data": card.get("data", ""),
        "findings": card.get("key_findings", []),
        "whyItMatters": card.get("why_it_matters", ""),
        "topics": card.get("topics", []),
        "industries": clean(ctx.get("industries")),
        "geographies": clean(ctx.get("geographies")),
        "basis": row["basis"],  # full_text | abstract_only
        "source": {"kind": "ai-pipeline", "model": row["model"], "prompt": row["prompt_version"],
                   "createdAt": row["created_at"][:10]},
    }


def protected(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        old = json.loads(path.read_text())
    except json.JSONDecodeError:
        return True
    src = ((old.get("summary") or {}).get("source") or {}).get("kind")
    return bool(old.get("locked")) or src == "claude-research"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing files (except protected ones)")
    args = ap.parse_args()
    if not DB.exists():
        sys.exit(f"No database at {DB}")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    faculty = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM faculty WHERE match_status='confirmed'")}
    slug_of = {fid: slugify(f["name"]) for fid, f in faculty.items()}
    isb_ids = {}
    for fid, f in faculty.items():
        for aid in (f["openalex_author_id"] or "").split("|"):
            if aid.strip():
                isb_ids[aid.strip().rsplit("/", 1)[-1]] = slug_of[fid]

    links: dict[int, set] = {}
    for r in conn.execute("SELECT paper_id, faculty_id FROM paper_authors"):
        if r["faculty_id"] in faculty:
            links.setdefault(r["paper_id"], set()).add(slug_of[r["faculty_id"]])

    cards = {r["paper_id"]: r for r in conn.execute(
        "SELECT * FROM paper_cards WHERE id IN (SELECT MAX(id) FROM paper_cards GROUP BY paper_id)")}

    groups: dict[str, list] = {}
    for r in conn.execute("SELECT * FROM papers"):
        if r["id"] not in links or not r["title"]:
            continue
        groups.setdefault(norm_title(r["title"]), []).append(r)

    (OUT / "papers").mkdir(parents=True, exist_ok=True)
    (OUT / "faculty").mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    for members in groups.values():
        members.sort(key=lambda r: (TYPE_RANK.get(r["type"], 9), -(r["year"] or 0)))
        primary = members[0]
        work = json.loads(primary["raw_json"])
        carded = [m for m in members if m["id"] in cards]
        carded.sort(key=lambda m: (cards[m["id"]]["basis"] != "full_text", -cards[m["id"]]["id"]))
        abstracts = [m["abstract"] for m in members if m["abstract"]]
        isb = sorted(set().union(*(links[m["id"]] for m in members)))
        paper = {
            "id": primary["openalex_work_id"],
            "title": primary["title"],
            "year": primary["year"],
            "date": primary["publication_date"],
            "type": primary["type"],
            "venue": primary["venue"],
            "doi": primary["doi"],
            "url": primary["landing_page_url"],
            "pdf": next((m["oa_pdf_url"] for m in members if m["oa_pdf_url"]), None),
            "citations": max(json.loads(m["raw_json"]).get("cited_by_count") or 0 for m in members),
            "authors": authors_of(work, isb_ids),
            "isb": isb,
            "abstract": max(abstracts, key=len) if abstracts else None,
            "summary": card_to_summary(json.loads(cards[carded[0]["id"]]["card_json"]), cards[carded[0]["id"]]) if carded else None,
            "versions": [{"id": m["openalex_work_id"], "type": m["type"], "venue": m["venue"], "year": m["year"],
                          "url": m["landing_page_url"] or m["doi"]} for m in members[1:]],
        }
        path = OUT / "papers" / f"{paper['id']}.json"
        if path.exists() and (not args.force or protected(path)):
            skipped += 1
            continue
        path.write_text(json.dumps(paper, indent=2, ensure_ascii=False) + "\n")
        written += 1

    for fid, f in faculty.items():
        path = OUT / "faculty" / f"{slug_of[fid]}.json"
        if path.exists() and (not args.force or protected(path)):
            continue
        prof = {
            "slug": slug_of[fid],
            "name": f["name"],
            "title": None,
            "area": f["area"],
            "homepage": f["homepage_url"],
            "openalex": [a for a in (f["openalex_author_id"] or "").split("|") if a],
            "photo": None,
            "profile": None,
        }
        path.write_text(json.dumps(prof, indent=2, ensure_ascii=False) + "\n")
    print(f"papers written: {written}, kept: {skipped}; faculty: {len(faculty)}")


if __name__ == "__main__":
    main()
