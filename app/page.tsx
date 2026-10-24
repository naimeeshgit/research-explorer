import Link from "next/link";
import { Suspense } from "react";
import Explorer, { HeroFallback } from "@/components/Explorer";
import { Avatar, Chips } from "@/components/ui";
import { getFaculty, papersOf, stats, topicCounts } from "@/lib/content";

export default function Home() {
  const faculty = getFaculty();
  const s = stats();
  const names = Object.fromEntries(faculty.map((f) => [f.slug, f.name]));
  const areas = Object.fromEntries(faculty.map((f) => [f.slug, f.area]));

  const landing = (
    <>
      <div className="stats">
        <div className="stat"><div className="n">{s.faculty}</div><div className="l">Professors</div></div>
        <div className="stat"><div className="n">{s.papers}</div><div className="l">Papers</div></div>
        <div className="stat"><div className="n">{s.summaries}</div><div className="l">Plain-English summaries</div></div>
        <div className="stat"><div className="n">{s.fullText}</div><div className="l">Read in full</div></div>
      </div>
      <div className="section">Faculty</div>
      <div className="grid">
        {faculty.map((f) => {
          const papers = papersOf(f.slug);
          const top = topicCounts(papers).slice(0, 4).map(([t]) => t);
          return (
            <div className="card" key={f.slug}>
              <div className="prof-card">
                <Avatar f={f} small />
                <div>
                  <h3><Link href={`/faculty/${f.slug}`}>{f.name}</Link></h3>
                  <div className="meta">
                    {f.area ? <span className="badge area">{f.area}</span> : null}
                    {papers.length} papers
                  </div>
                  <Chips items={top} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );

  return (
    <Suspense
      fallback={
        <>
          <HeroFallback />
          {landing}
        </>
      }
    >
      <Explorer names={names} areas={areas}>{landing}</Explorer>
    </Suspense>
  );
}
