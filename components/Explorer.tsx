"use client";

import Link from "next/link";
import MiniSearch from "minisearch";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SearchDoc } from "@/lib/types";

const SUGGESTED = ["Zombie lending", "TB diagnosis", "IPO pricing", "Currency hedging", "Hospital operations", "Outsourcing"];

export function Hero({
  q,
  onChange,
  onSubmit,
  onPick,
}: {
  q: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onPick: (v: string) => void;
}) {
  return (
    <section className="hero">
      <div className="eyebrow">Indian School of Business · Faculty research</div>
      <h1>
        Find the research behind
        <br />
        the people who teach you.
      </h1>
      <p>
        Search a topic to see which ISB professors work on it, read plain-English summaries of their papers, and know
        what to ask them about.
      </p>
      <div className="search">
        <span className="icon" aria-hidden>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        </span>
        <input
          type="search"
          value={q}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSubmit()}
          placeholder="Search a topic, e.g. zombie lending, TB diagnosis, IPO pricing…"
          aria-label="Search topics"
          autoComplete="off"
        />
        {q ? (
          <button className="clear" onClick={() => onPick("")} aria-label="Clear search">
            ×
          </button>
        ) : null}
      </div>
      <div className="suggest">
        {SUGGESTED.map((s) => (
          <button key={s} onClick={() => onPick(s)}>
            {s}
          </button>
        ))}
      </div>
    </section>
  );
}

type Hit = SearchDoc & { score: number };

function useIndex() {
  const [index, setIndex] = useState<MiniSearch<SearchDoc> | null>(null);
  useEffect(() => {
    let alive = true;
    fetch("/search-index.json")
      .then((r) => r.json())
      .then((docs: SearchDoc[]) => {
        const ms = new MiniSearch<SearchDoc>({
          fields: ["title", "topics", "oneLiner", "overview", "abstract", "venue"],
          storeFields: ["id", "kind", "title", "year", "venue", "isb", "oneLiner", "basis"],
          searchOptions: { boost: { title: 3, topics: 2.5, oneLiner: 1.5 }, prefix: true, fuzzy: 0.15, combineWith: "AND" },
        });
        ms.addAll(docs);
        if (alive) setIndex(ms);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return index;
}

function runSearch(index: MiniSearch<SearchDoc>, q: string): Hit[] {
  let hits = index.search(q) as unknown as Hit[];
  if (hits.length === 0) hits = index.search(q, { combineWith: "OR" }) as unknown as Hit[];
  // One row per title: working-paper copies are merged at export, this is a safety net.
  const seen = new Set<string>();
  return hits.filter((h) => {
    const k = h.title.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function rankFaculty(hits: Hit[], top = 3) {
  const by = new Map<string, Hit[]>();
  for (const h of hits) for (const s of h.isb ?? []) by.set(s, [...(by.get(s) ?? []), h]);
  return [...by.entries()]
    .map(([slug, hs]) => ({ slug, score: hs.slice(0, top).reduce((a, h) => a + h.score, 0), papers: hs.slice(0, top), n: hs.length }))
    .sort((a, b) => b.score - a.score);
}

export default function Explorer({
  names,
  areas,
  children,
}: {
  names: Record<string, string>;
  areas: Record<string, string | null>;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const [q, setQ] = useState(urlQ);
  const index = useIndex();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setQ(urlQ), [urlQ]);

  const update = (value: string, immediate = false) => {
    setQ(value);
    if (timer.current) clearTimeout(timer.current);
    const push = () => router.replace(value.trim() ? `/?q=${encodeURIComponent(value.trim())}` : "/", { scroll: false });
    if (immediate) push();
    else timer.current = setTimeout(push, 350);
  };

  const query = q.trim();
  const hits = useMemo(() => (index && query.length > 1 ? runSearch(index, query) : []), [index, query]);
  const profs = useMemo(() => rankFaculty(hits), [hits]);

  return (
    <>
      <Hero q={q} onChange={(v) => update(v)} onSubmit={() => update(q, true)} onPick={(v) => update(v, true)} />

      {query.length > 1 ? (
        !index ? (
          <div className="empty">Loading search…</div>
        ) : hits.length === 0 ? (
          <div className="notice">
            No papers match <b>{query}</b>. Try a broader word, or one of the suggested topics.
          </div>
        ) : (
          <>
            <div className="section">Professors working on “{query}”</div>
            <div className="grid">
              {profs.slice(0, 6).map((r) => (
                <div className="card" key={r.slug}>
                  <div className="prof-card">
                    <div className="avatar sm" aria-hidden>
                      {(names[r.slug] ?? r.slug)
                        .split(/\s+/)
                        .filter((_, i, a) => i === 0 || i === a.length - 1)
                        .map((w) => w[0])
                        .join("")}
                    </div>
                    <div>
                      <h3>
                        <Link href={`/faculty/${r.slug}`}>{names[r.slug] ?? r.slug}</Link>
                      </h3>
                      <div className="meta">
                        {areas[r.slug] ? <span className="badge area">{areas[r.slug]}</span> : null}
                        {r.n} matching {r.n === 1 ? "paper" : "papers"}
                      </div>
                      <div className="why">
                        {r.papers.map((p) => (
                          <div key={p.id}>
                            · <Link href={`/papers/${p.id}`}>{p.title}</Link>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="section">Papers · {hits.length} results</div>
            {hits.slice(0, 40).map((h) => (
              <div className="card" key={h.id}>
                <h3>
                  <Link href={`/papers/${h.id}`}>{h.title}</Link>
                </h3>
                <div className="meta">
                  {h.basis === "full_text" ? (
                    <span className="badge full">Read in full</span>
                  ) : h.basis ? (
                    <span className="badge abstract">From abstract</span>
                  ) : (
                    <span className="badge none">No summary yet</span>
                  )}
                  {[h.year, h.venue].filter(Boolean).join(" · ")}
                </div>
                {h.oneLiner ? <div className="lead">{h.oneLiner}</div> : null}
                <div className="why">
                  ISB:{" "}
                  {(h.isb ?? []).map((s, i) => (
                    <span key={s}>
                      {i ? " · " : ""}
                      <Link href={`/faculty/${s}`}>{names[s] ?? s}</Link>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </>
        )
      ) : (
        children
      )}
    </>
  );
}

/** Server-rendered placeholder shown until the client reads the URL's ?q=. */
export function HeroFallback() {
  const noop = () => {};
  return <Hero q="" onChange={noop} onSubmit={noop} onPick={noop} />;
}
