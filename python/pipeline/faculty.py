"""Part 1: match faculty.csv rows to OpenAlex author IDs.

IDs typed into faculty.csv are trusted and never replaced. scholar_url is carried
through for human reviewers only and is never fetched.
"""
import csv
import json
import math
import re
import unicodedata

from rapidfuzz import fuzz

import config
from pipeline import db, openalex

AUTHOR_FIELDS = ",".join([
    "id", "display_name", "display_name_alternatives", "orcid", "works_count",
    "cited_by_count", "last_known_institutions", "affiliations",
])
HONORIFICS = {"prof", "professor", "dr", "mr", "ms", "mrs"}


# --- Institutions ----------------------------------------------------------------

def list_institutions(query: str = "Indian School of Business") -> list[dict]:
    data = openalex.get("/institutions", {
        "search": query, "per_page": 25,
        "select": "id,display_name,display_name_alternatives,country_code,geo,type,works_count,ror",
    })
    rows = data.get("results") or []
    print(f"Institutions matching {query!r}: {len(rows)}")
    for r in rows:
        geo = r.get("geo") or {}
        print(f"  {openalex.short_id(r['id']):>12}  {r['display_name']}  |  "
              f"{geo.get('city')}, {r.get('country_code')}  |  {r.get('works_count')} works  |  {r.get('type')}")
    print(f"Currently configured ISB_INSTITUTION_IDS = {config.ISB_INSTITUTION_IDS}")
    return rows


# --- Name matching ----------------------------------------------------------------

def normalize_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-zA-Z\s]", " ", name.lower())
    return " ".join(t for t in name.split() if t not in HONORIFICS)


def name_similarity(a: str, b: str) -> float:
    """0-1. Token order is ignored; middle initials are tolerated."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    score = fuzz.token_sort_ratio(na, nb)
    strip = lambda s: " ".join(t for t in s.split() if len(t) > 1)
    sa, sb = strip(na), strip(nb)
    if sa and sb:
        score = max(score, fuzz.token_sort_ratio(sa, sb))
    return score / 100.0


def isb_affiliation(author: dict) -> str:
    """'current', 'past', or 'none'."""
    isb = set(config.ISB_INSTITUTION_IDS)
    if any(openalex.short_id(i.get("id")) in isb for i in author.get("last_known_institutions") or []):
        return "current"
    if any(openalex.short_id((a.get("institution") or {}).get("id")) in isb for a in author.get("affiliations") or []):
        return "past"
    return "none"


def isb_years(author: dict) -> list[int]:
    isb = set(config.ISB_INSTITUTION_IDS)
    years: set[int] = set()
    for a in author.get("affiliations") or []:
        if openalex.short_id((a.get("institution") or {}).get("id")) in isb:
            years.update(y for y in a.get("years") or [] if 1900 <= y <= 2100)
    return sorted(years)


def affiliation_summary(author: dict, limit: int = 5) -> str:
    parts = []
    for a in (author.get("affiliations") or [])[:limit]:
        inst = a.get("institution") or {}
        yrs = sorted(y for y in a.get("years") or [] if 1900 <= y <= 2100)
        span = f"{yrs[0]}-{yrs[-1]}" if yrs else "?"
        parts.append(f"{inst.get('display_name')} ({span})")
    return "; ".join(parts)


def score_candidate(faculty_name: str, author: dict) -> dict:
    names = [author.get("display_name") or ""] + list(author.get("display_name_alternatives") or [])
    sim = max(name_similarity(faculty_name, n) for n in names)
    isb = isb_affiliation(author)
    works = author.get("works_count") or 0
    isb_score = {"current": 1.0, "past": 0.7, "none": 0.0}[isb]
    works_score = min(1.0, math.log10(works + 1) / 2)  # 100+ works -> 1.0
    total = 0.6 * sim + 0.3 * isb_score + 0.1 * works_score
    strong = sim >= config.MATCH_STRONG_NAME_SIM and isb != "none" and works >= config.MATCH_MIN_WORKS
    return {
        "id": openalex.short_id(author["id"]),
        "display_name": author.get("display_name"),
        "name_sim": round(sim, 3),
        "isb": isb,
        "isb_years": isb_years(author),
        "works_count": works,
        "cited_by_count": author.get("cited_by_count"),
        "orcid": author.get("orcid"),
        "affiliations": affiliation_summary(author),
        "score": round(total, 3),
        "strong": strong,
    }


def find_candidates(name: str, use_cache: bool = True) -> list[dict]:
    """Search authors by name, restricted to ISB-affiliated authors (current or past).
    Falls back to an unrestricted search only to surface close-name candidates for review."""
    inst_filter = "affiliations.institution.id:" + "|".join(config.ISB_INSTITUTION_IDS)
    query = normalize_name(name)
    params = {"search": query, "filter": inst_filter, "per_page": 25, "select": AUTHOR_FIELDS}
    results = openalex.get("/authors", params, use_cache=use_cache).get("results") or []
    cands = [score_candidate(name, a) for a in results]
    cands = [c for c in cands if c["name_sim"] >= 0.6]
    if not cands:
        params = {"search": query, "per_page": 25, "select": AUTHOR_FIELDS}
        results = openalex.get("/authors", params, use_cache=use_cache).get("results") or []
        cands = [score_candidate(name, a) for a in results]
        cands = [c for c in cands if c["name_sim"] >= 0.85]
    cands.sort(key=lambda c: (c["strong"], c["score"]), reverse=True)
    return cands


def decide(cands: list[dict]) -> tuple[str, str | None]:
    strong = [c for c in cands if c["strong"]]
    if len(strong) == 1:
        return "confirmed", strong[0]["id"]
    if cands:
        return "needs_review", None
    return "not_found", None


# --- CSV ----------------------------------------------------------------------------

def read_faculty_csv(path=None) -> list[dict]:
    path = path or config.FACULTY_CSV
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Create it with the header:\n"
            "name,area,homepage_url,scholar_url,openalex_author_id"
        )
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            name = row.get("name", "")
            if not name:
                continue
            if name.lower() in seen:
                print(f"  WARNING: duplicate name on line {i} of {path.name}: {name!r} (skipped)")
                continue
            seen.add(name.lower())
            rows.append(row)
    return rows


# --- Main step ---------------------------------------------------------------------

def run(use_cache: bool = True) -> None:
    if not config.ISB_INSTITUTION_IDS:
        list_institutions()
        raise SystemExit("Set ISB_INSTITUTION_IDS in config.py first.")

    conn = db.connect()
    rows = read_faculty_csv()
    counts = {"confirmed": 0, "needs_review": 0, "not_found": 0}
    report_rows: list[dict] = []
    known_ids: set[str] = set()

    with db.run(conn, "faculty") as stats:
        for row in rows:
            name = row["name"]
            provided_ids = openalex.split_ids(row.get("openalex_author_id"))
            if provided_ids:
                # One person can have several OpenAlex profiles: "A1|A2" in the CSV.
                chosen = "|".join(provided_ids)
                status, cands, warnings = "confirmed", [], []
                notes = {"source": "faculty.csv"}
                for pid in provided_ids:
                    try:
                        author = openalex.get_author(pid, use_cache=use_cache)
                        cands.append(score_candidate(name, author))
                        resolved = openalex.short_id(author["id"])
                        if resolved != pid:
                            warnings.append(f"OpenAlex redirects {pid} -> {resolved} (merged profile)")
                    except openalex.OpenAlexError as e:
                        warnings.append(f"provided ID {pid} could not be fetched: {e}")
                if warnings:
                    notes["warning"] = "; ".join(warnings)
                    print(f"  WARNING {name}: {notes['warning']}")
            else:
                cands = find_candidates(name, use_cache=use_cache)
                status, chosen = decide(cands)
                notes = {"source": "auto",
                         "candidates": [{k: c[k] for k in ("id", "display_name", "name_sim", "isb",
                                                           "works_count", "score")}
                                        for c in cands[:config.MATCH_MAX_CANDIDATES]]}

            counts[status] += 1
            if chosen:
                known_ids.update(openalex.split_ids(chosen))
            conn.execute(
                """INSERT INTO faculty (name, area, homepage_url, scholar_url, openalex_author_id,
                                        match_status, match_notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       area = excluded.area, homepage_url = excluded.homepage_url,
                       scholar_url = excluded.scholar_url,
                       openalex_author_id = excluded.openalex_author_id,
                       match_status = excluded.match_status, match_notes = excluded.match_notes""",
                (name, row.get("area") or None, row.get("homepage_url") or None,
                 row.get("scholar_url") or None, chosen, status, json.dumps(notes)),
            )
            conn.commit()
            marker = {"confirmed": "OK ", "needs_review": "?? ", "not_found": "-- "}[status]
            print(f"  {marker}{name:<35} {status:<13} {chosen or ''}  ({len(cands)} candidate(s))")

            base = {"name": name, "status": status, "chosen_id": chosen or "",
                    "chosen_openalex_url": f"https://openalex.org/authors/{chosen}" if chosen else "",
                    "source": notes["source"], "scholar_url": row.get("scholar_url", ""),
                    "warning": notes.get("warning", "")}
            if not cands:
                report_rows.append(base)
            for rank, c in enumerate(cands[:config.MATCH_MAX_CANDIDATES], start=1):
                report_rows.append({**base, "candidate_rank": rank, "candidate_id": c["id"],
                                    "candidate_display_name": c["display_name"],
                                    "candidate_score": c["score"], "name_similarity": c["name_sim"],
                                    "isb_affiliation": c["isb"],
                                    "isb_years": " ".join(map(str, c["isb_years"])),
                                    "strong": c["strong"], "works_count": c["works_count"],
                                    "cited_by_count": c["cited_by_count"], "orcid": c["orcid"] or "",
                                    "affiliations": c["affiliations"],
                                    "openalex_url": f"https://openalex.org/authors/{c['id']}"})

        csv_names = {r["name"] for r in rows}
        orphans = [r["name"] for r in conn.execute("SELECT name FROM faculty") if r["name"] not in csv_names]
        if orphans:
            print(f"  NOTE: {len(orphans)} faculty in the database are no longer in faculty.csv "
                  f"(left untouched): {', '.join(orphans[:10])}")

        write_resolution_report(report_rows)
        n_missing = write_possibly_missing(conn, known_ids, [r["name"] for r in rows], use_cache)

        stats.update(counts, total=len(rows), possibly_missing=n_missing,
                     openalex_cost_usd=round(openalex.spent_usd, 4))

    print()
    print(f"Faculty: {len(rows)}  |  confirmed {counts['confirmed']}  |  "
          f"needs_review {counts['needs_review']}  |  not_found {counts['not_found']}")
    print(f"Possibly missing ISB authors (>= {config.POSSIBLY_MISSING_MIN_WORKS} works, not in CSV): {n_missing}")
    print(f"OpenAlex usage this run: ${openalex.spent_usd:.4f} (cached responses cost nothing)")
    print(f"Reports: reports/faculty_resolution.csv, reports/possibly_missing_faculty.csv")


RESOLUTION_COLUMNS = [
    "name", "status", "chosen_id", "chosen_openalex_url", "source", "warning",
    "candidate_rank", "candidate_id", "candidate_display_name", "candidate_score",
    "name_similarity", "isb_affiliation", "isb_years", "strong", "works_count",
    "cited_by_count", "orcid", "affiliations", "openalex_url", "scholar_url",
]


def write_resolution_report(rows: list[dict]) -> None:
    config.REPORTS_DIR.mkdir(exist_ok=True)
    order = {"needs_review": 0, "not_found": 1, "confirmed": 2}
    rows = sorted(rows, key=lambda r: (order[r["status"]], r["name"], r.get("candidate_rank", 0)))
    with open(config.REPORTS_DIR / "faculty_resolution.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESOLUTION_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_possibly_missing(conn, known_ids: set[str], faculty_names: list[str], use_cache: bool) -> int:
    """ISB-affiliated OpenAlex authors with >= N works who aren't matched to anyone in
    faculty.csv. For review only; nothing is added automatically."""
    inst_filter = "affiliations.institution.id:" + "|".join(config.ISB_INSTITUTION_IDS)
    params = {"filter": f"{inst_filter},works_count:>{config.POSSIBLY_MISSING_MIN_WORKS - 1}",
              "select": AUTHOR_FIELDS}
    out = []
    for a in openalex.iterate("/authors", params, use_cache=use_cache):
        aid = openalex.short_id(a["id"])
        if aid in known_ids:
            continue
        best_name, best_sim = "", 0.0
        for fn in faculty_names:
            s = name_similarity(fn, a.get("display_name") or "")
            if s > best_sim:
                best_name, best_sim = fn, s
        lki = "; ".join(i.get("display_name") or "" for i in a.get("last_known_institutions") or [])
        out.append({
            "author_id": aid, "display_name": a.get("display_name"),
            "works_count": a.get("works_count"), "cited_by_count": a.get("cited_by_count"),
            "isb_affiliation": isb_affiliation(a),
            "isb_years": " ".join(map(str, isb_years(a))),
            "last_known_institutions": lki,
            "similar_faculty_name": best_name if best_sim >= 0.85 else "",
            "similarity": round(best_sim, 3) if best_sim >= 0.85 else "",
            "openalex_url": f"https://openalex.org/authors/{aid}",
        })
    out.sort(key=lambda r: (r["isb_affiliation"] != "current", -(r["works_count"] or 0)))
    config.REPORTS_DIR.mkdir(exist_ok=True)
    with open(config.REPORTS_DIR / "possibly_missing_faculty.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["author_id"])
        w.writeheader()
        w.writerows(out)
    return len(out)
