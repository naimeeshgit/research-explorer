import Link from "next/link";
import type { Faculty, Paper, Summary } from "@/lib/types";

export function initials(name: string) {
  const parts = name.split(/\s+/).filter(Boolean);
  const pick = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts;
  return pick.map((p) => p[0]).join("").toUpperCase();
}

export function Avatar({ f, small }: { f: Pick<Faculty, "name" | "photo">; small?: boolean }) {
  if (f.photo) return <img className={`avatar${small ? " sm" : ""}`} src={f.photo} alt={f.name} />;
  return <div className={`avatar${small ? " sm" : ""}`} aria-hidden>{initials(f.name)}</div>;
}

export function BasisBadge({ summary }: { summary: Summary | null | undefined }) {
  if (!summary) return <span className="badge none">No summary yet</span>;
  if (summary.basis === "full_text") return <span className="badge full">Read in full</span>;
  if (summary.basis === "published_sources") return <span className="badge full">Researched</span>;
  return <span className="badge abstract">From abstract</span>;
}

export function Chips({ items, counts, link = true }: { items: string[]; counts?: Map<string, number>; link?: boolean }) {
  if (!items.length) return null;
  return (
    <div className="chips">
      {items.map((t) =>
        link ? (
          <Link key={t} className="chip" href={`/?q=${encodeURIComponent(t)}`}>
            {t}
            {counts && (counts.get(t) ?? 0) > 1 ? <b>{counts.get(t)}</b> : null}
          </Link>
        ) : (
          <span key={t} className="chip">{t}</span>
        ),
      )}
    </div>
  );
}

export function PaperCard({ p, names, showFaculty = true }: { p: Paper; names: Record<string, string>; showFaculty?: boolean }) {
  return (
    <div className="card">
      <h3>
        <Link href={`/papers/${p.id}`}>{p.title}</Link>
      </h3>
      <div className="meta">
        <BasisBadge summary={p.summary} />
        {[p.year, p.venue].filter(Boolean).join(" · ")}
      </div>
      {p.summary ? <div className="lead">{p.summary.oneLiner}</div> : null}
      {showFaculty ? (
        <div className="why">
          ISB:{" "}
          {p.isb.map((s, i) => (
            <span key={s}>
              {i ? " · " : ""}
              <Link href={`/faculty/${s}`}>{names[s] ?? s}</Link>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
