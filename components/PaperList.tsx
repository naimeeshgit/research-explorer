"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

export interface ListItem {
  id: string;
  title: string;
  year: number | null;
  venue: string | null;
  citations: number;
  oneLiner: string | null;
  basis: string | null;
}

type Sort = "newest" | "cited";

export default function PaperList({ items }: { items: ListItem[] }) {
  const [filter, setFilter] = useState("");
  const [onlySummaries, setOnlySummaries] = useState(false);
  const [sort, setSort] = useState<Sort>("newest");

  const shown = useMemo(() => {
    const f = filter.toLowerCase().trim();
    const out = items.filter(
      (p) =>
        (!onlySummaries || p.basis) &&
        (!f || p.title.toLowerCase().includes(f) || (p.oneLiner ?? "").toLowerCase().includes(f) || (p.venue ?? "").toLowerCase().includes(f)),
    );
    if (sort === "cited") out.sort((a, b) => b.citations - a.citations);
    return out;
  }, [items, filter, onlySummaries, sort]);

  return (
    <>
      <div className="toolbar">
        <input type="search" placeholder="Filter these papers…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter papers" />
        <div className="seg" role="group" aria-label="Sort">
          <button className={sort === "newest" ? "on" : ""} onClick={() => setSort("newest")}>Newest</button>
          <button className={sort === "cited" ? "on" : ""} onClick={() => setSort("cited")}>Most cited</button>
        </div>
        <div className="seg" role="group" aria-label="Show">
          <button className={!onlySummaries ? "on" : ""} onClick={() => setOnlySummaries(false)}>All</button>
          <button className={onlySummaries ? "on" : ""} onClick={() => setOnlySummaries(true)}>With summary</button>
        </div>
      </div>
      {shown.length === 0 ? <div className="notice soft">No papers match that filter.</div> : null}
      {shown.map((p) => (
        <div className="card" key={p.id}>
          <h3><Link href={`/papers/${p.id}`}>{p.title}</Link></h3>
          <div className="meta">
            {p.basis === "full_text" ? <span className="badge full">Read in full</span>
              : p.basis === "published_sources" ? <span className="badge full">Researched</span>
              : p.basis ? <span className="badge abstract">From abstract</span>
              : <span className="badge none">No summary yet</span>}
            {[p.year, p.venue].filter(Boolean).join(" · ")}
            {p.citations > 0 ? <span>· {p.citations.toLocaleString()} citations</span> : null}
          </div>
          {p.oneLiner ? <div className="lead">{p.oneLiner}</div> : null}
        </div>
      ))}
    </>
  );
}
