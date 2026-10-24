"""Part 2: fetch every work by every confirmed professor and store it with its raw JSON.

Papers are upserted by openalex_work_id; updated_at only moves when the raw JSON changes.
No merging of working-paper / journal versions happens here (title_normalized is stored
for a later version to use).
"""
import csv
import html
import json
import random
import re
import unicodedata
from collections import Counter

import config
from pipeline import db, openalex


# --- Field extraction ---------------------------------------------------------------

def rebuild_abstract(inverted_index: dict | None) -> str | None:
    if not inverted_index:
        return None
    positions = [(pos, word) for word, poss in inverted_index.items() for pos in poss]
    text = " ".join(word for _, word in sorted(positions)).strip()
    return text or None


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", title))
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip() or None


def clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I).lower()


def pick_venue(work: dict) -> str | None:
    for loc in [work.get("primary_location")] + list(work.get("locations") or []):
        if not loc:
            continue
        src = loc.get("source") or {}
        if src.get("display_name"):
            return src["display_name"]
    for loc in work.get("locations") or []:
        if loc.get("raw_source_name"):
            return loc["raw_source_name"]
    return None


def pick_oa_pdf_url(work: dict) -> str | None:
    best = work.get("best_oa_location") or {}
    if best.get("pdf_url"):
        return best["pdf_url"]
    for loc in work.get("locations") or []:
        if loc.get("pdf_url"):
            return loc["pdf_url"]
    return None


def pick_landing_page(work: dict) -> str | None:
    primary = work.get("primary_location") or {}
    return primary.get("landing_page_url") or work.get("doi")


def paper_fields(work: dict) -> dict:
    title = work.get("title") or work.get("display_name")
    return {
        "openalex_work_id": openalex.short_id(work["id"]),
        "doi": clean_doi(work.get("doi")),
        "title": title,
        "title_normalized": normalize_title(title),
        "publication_date": work.get("publication_date"),
        "year": work.get("publication_year"),
        "type": work.get("type"),
        "venue": pick_venue(work),
        "abstract": rebuild_abstract(work.get("abstract_inverted_index")),
        "is_oa": int(bool((work.get("open_access") or {}).get("is_oa"))),
        "oa_pdf_url": pick_oa_pdf_url(work),
        "landing_page_url": pick_landing_page(work),
        "locations_json": json.dumps(work.get("locations") or []),
        "raw_json": json.dumps(work, sort_keys=True),
    }


# --- Storage ------------------------------------------------------------------------

def upsert_paper(conn, work: dict) -> tuple[int, str]:
    """Returns (paper_id, 'inserted' | 'updated' | 'unchanged')."""
    f = paper_fields(work)
    ts = db.now()
    row = conn.execute("SELECT id, raw_json FROM papers WHERE openalex_work_id = ?",
                       (f["openalex_work_id"],)).fetchone()
    if row is None:
        cols = list(f) + ["fetched_at", "updated_at"]
        cur = conn.execute(
            f"INSERT INTO papers ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [*f.values(), ts, ts],
        )
        return cur.lastrowid, "inserted"
    if row["raw_json"] == f["raw_json"]:
        conn.execute("UPDATE papers SET fetched_at = ? WHERE id = ?", (ts, row["id"]))
        return row["id"], "unchanged"
    sets = ", ".join(f"{k} = ?" for k in f)
    conn.execute(f"UPDATE papers SET {sets}, fetched_at = ?, updated_at = ? WHERE id = ?",
                 [*f.values(), ts, ts, row["id"]])
    return row["id"], "updated"


def author_position(work: dict, author_ids: set[str]) -> str | None:
    for a in work.get("authorships") or []:
        if openalex.short_id((a.get("author") or {}).get("id")) in author_ids:
            return a.get("author_position")
    return None


# --- Main step ----------------------------------------------------------------------

def run(use_cache: bool = True) -> None:
    conn = db.connect()
    faculty = conn.execute(
        "SELECT id, name, openalex_author_id FROM faculty "
        "WHERE match_status = 'confirmed' AND openalex_author_id IS NOT NULL ORDER BY name"
    ).fetchall()
    if not faculty:
        print("No confirmed faculty. Run `python -m pipeline faculty` and resolve the report first.")
        return

    allowed = set(config.WORK_TYPES_ALLOWED)
    totals = Counter()
    skipped_types = Counter()

    with db.run(conn, "works") as stats:
        # Links for faculty who are no longer confirmed are stale.
        n = conn.execute("DELETE FROM paper_authors WHERE faculty_id NOT IN "
                         "(SELECT id FROM faculty WHERE match_status = 'confirmed')").rowcount
        if n:
            print(f"  removed {n} links for faculty who are no longer confirmed")

        for fac in faculty:
            ids = openalex.split_ids(fac["openalex_author_id"])
            params = {"filter": "authorships.author.id:" + "|".join(ids)}
            linked: dict[int, str | None] = {}
            c = Counter()
            for work in openalex.iterate("/works", params, use_cache=use_cache):
                if work.get("type") not in allowed or work.get("is_paratext"):
                    skipped_types[work.get("type")] += 1
                    c["skipped"] += 1
                    continue
                paper_id, action = upsert_paper(conn, work)
                c[action] += 1
                linked[paper_id] = author_position(work, set(ids))

            # Replace this professor's links with exactly what OpenAlex returned.
            existing = {r["paper_id"] for r in conn.execute(
                "SELECT paper_id FROM paper_authors WHERE faculty_id = ?", (fac["id"],))}
            stale = existing - linked.keys()
            conn.executemany("DELETE FROM paper_authors WHERE faculty_id = ? AND paper_id = ?",
                             [(fac["id"], p) for p in stale])
            conn.executemany(
                "INSERT INTO paper_authors (paper_id, faculty_id, author_position) VALUES (?, ?, ?) "
                "ON CONFLICT(paper_id, faculty_id) DO UPDATE SET author_position = excluded.author_position",
                [(p, fac["id"], pos) for p, pos in linked.items()],
            )
            conn.commit()
            totals.update(c)
            totals["links_removed"] += len(stale)
            print(f"  {fac['name']:<35} {len(linked):>4} papers  (+{c['inserted']} new, "
                  f"{c['updated']} changed, {c['unchanged']} unchanged, {c['skipped']} skipped by type)")

        stats.update(faculty=len(faculty), **totals, skipped_types=dict(skipped_types),
                     openalex_cost_usd=round(openalex.spent_usd, 4))

    print()
    print(f"Works: {totals['inserted']} new, {totals['updated']} changed, {totals['unchanged']} unchanged, "
          f"{totals['skipped']} skipped by type")
    if skipped_types:
        print("Skipped types: " + ", ".join(f"{t} {n}" for t, n in skipped_types.most_common()))
    print(f"OpenAlex usage this run: ${openalex.spent_usd:.4f}")
    report(conn)


def report(conn, spot_check: list[str] | None = None, n_spot: int = 3) -> None:
    rows = conn.execute("""
        SELECT f.name, COUNT(p.id) AS n,
               SUM(p.abstract IS NOT NULL) AS n_abs,
               SUM(p.oa_pdf_url IS NOT NULL) AS n_pdf,
               MIN(p.year) AS first_year, MAX(p.year) AS last_year
        FROM faculty f
        LEFT JOIN paper_authors pa ON pa.faculty_id = f.id
        LEFT JOIN papers p ON p.id = pa.paper_id
        WHERE f.match_status = 'confirmed'
        GROUP BY f.id ORDER BY f.name
    """).fetchall()
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "-"

    out = []
    print()
    print(f"{'professor':<35} {'papers':>6} {'abstract':>9} {'OA PDF':>7}  years")
    for r in rows:
        n, na, npdf = r["n"], r["n_abs"] or 0, r["n_pdf"] or 0
        years = f"{r['first_year']}-{r['last_year']}" if n else ""
        print(f"{r['name']:<35} {n:>6} {pct(na, n):>9} {pct(npdf, n):>7}  {years}")
        out.append({"name": r["name"], "papers": n, "with_abstract": na, "pct_abstract": pct(na, n),
                    "with_oa_pdf_url": npdf, "pct_oa_pdf_url": pct(npdf, n), "first_year": r["first_year"],
                    "last_year": r["last_year"]})
    tot = conn.execute("SELECT COUNT(*) n, SUM(abstract IS NOT NULL) a, SUM(oa_pdf_url IS NOT NULL) p "
                       "FROM papers WHERE id IN (SELECT paper_id FROM paper_authors)").fetchone()
    shared = conn.execute("SELECT COUNT(*) FROM (SELECT paper_id FROM paper_authors "
                          "GROUP BY paper_id HAVING COUNT(*) > 1)").fetchone()[0]
    print(f"{'ALL (distinct papers)':<35} {tot['n']:>6} {pct(tot['a'] or 0, tot['n']):>9} "
          f"{pct(tot['p'] or 0, tot['n']):>7}")
    print(f"Papers shared by 2+ ISB professors: {shared}")

    config.REPORTS_DIR.mkdir(exist_ok=True)
    with open(config.REPORTS_DIR / "works_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["name"])
        w.writeheader()
        w.writerows(out)

    names = spot_check or random.sample([r["name"] for r in rows if r["n"]], min(n_spot, sum(1 for r in rows if r["n"])))
    for name in names:
        recent = conn.execute("""
            SELECT p.title, p.year, p.publication_date, p.venue, p.type FROM papers p
            JOIN paper_authors pa ON pa.paper_id = p.id JOIN faculty f ON f.id = pa.faculty_id
            WHERE f.name = ? ORDER BY p.publication_date DESC LIMIT 5""", (name,)).fetchall()
        print(f"\nSpot-check: {name}, 5 most recent (compare with their homepage)")
        if not recent:
            print("  (no papers, or name not found)")
        for p in recent:
            print(f"  {p['year']}  {(p['title'] or '')[:90]}")
            print(f"        {p['venue'] or '(no venue)'}  [{p['type']}]")
    print("\nReport: reports/works_summary.csv")
