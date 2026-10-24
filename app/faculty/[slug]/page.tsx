import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import PaperList from "@/components/PaperList";
import { Avatar, Chips } from "@/components/ui";
import { getFaculty, getFacultyBySlug, getPaper, papersOf, topicCounts } from "@/lib/content";

export const dynamicParams = false;

export function generateStaticParams() {
  return getFaculty().map((f) => ({ slug: f.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const f = getFacultyBySlug((await params).slug);
  return f ? { title: f.name, description: f.profile?.summary ?? `Research by ${f.name}, ${f.area ?? ""} at ISB.` } : {};
}

export default async function FacultyPage({ params }: { params: Promise<{ slug: string }> }) {
  const f = getFacultyBySlug((await params).slug);
  if (!f) notFound();
  const papers = papersOf(f.slug);
  const summarised = papers.filter((p) => p.summary);
  const years = papers.map((p) => p.year).filter((y): y is number => !!y);
  const topics = topicCounts(papers);
  const counts = new Map(topics);

  return (
    <>
      <div className="crumbs"><Link href="/">Home</Link> / <Link href="/faculty">Faculty</Link> / {f.name}</div>
      <div className="prof-head">
        <Avatar f={f} />
        <div>
          <h1>{f.name}</h1>
          <div className="meta">
            {f.area ? <span className="badge area">{f.area}</span> : null}
            {f.title ? <span>{f.title}</span> : null}
            {f.homepage ? <a href={f.homepage} target="_blank" rel="noreferrer">Homepage ↗</a> : null}
          </div>
        </div>
      </div>

      <div className="stats">
        <div className="stat"><div className="n">{papers.length}</div><div className="l">Papers</div></div>
        <div className="stat"><div className="n">{summarised.length}</div><div className="l">With summaries</div></div>
        <div className="stat"><div className="n">{papers.reduce((a, p) => a + p.citations, 0).toLocaleString()}</div><div className="l">Citations (OpenAlex)</div></div>
        <div className="stat"><div className="n">{years.length ? `${Math.min(...years)}–${Math.max(...years)}` : "—"}</div><div className="l">Years</div></div>
      </div>

      <div className="section">Research summary</div>
      {f.profile ? (
        <>
          <div className="lead">{f.profile.summary}</div>
          {f.profile.themes.length ? (
            <>
              <div className="section">Core themes</div>
              <div className="grid">
                {f.profile.themes.map((t) => (
                  <div className="card" key={t.name}>
                    <h3>{t.name}</h3>
                    <div className="lead" style={{ fontSize: ".93rem" }}>{t.description}</div>
                    <div className="why">
                      {t.papers.map((id) => getPaper(id)).filter(Boolean).map((p) => (
                        <div key={p!.id}>· <Link href={`/papers/${p!.id}`}>{p!.title}</Link></div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {f.profile.talkTo.length ? (
            <>
              <div className="section">Good to talk to about</div>
              <Chips items={f.profile.talkTo} link={false} />
            </>
          ) : null}
        </>
      ) : (
        <div className="notice soft">A research profile for {f.name} is being written. Until then, the topics below come straight from the paper summaries.</div>
      )}

      {topics.length ? (
        <>
          <div className="section">Frequent topics</div>
          <Chips items={topics.slice(0, 14).map(([t]) => t)} counts={counts} />
        </>
      ) : null}

      <div className="section">Papers · {papers.length}</div>
      <PaperList
        items={papers.map((p) => ({
          id: p.id,
          title: p.title,
          year: p.year,
          venue: p.venue,
          citations: p.citations,
          oneLiner: p.summary?.oneLiner ?? null,
          basis: p.summary?.basis ?? null,
        }))}
      />
    </>
  );
}
