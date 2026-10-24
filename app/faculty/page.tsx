import Link from "next/link";
import type { Metadata } from "next";
import { Avatar, Chips } from "@/components/ui";
import { getFaculty, papersOf, topicCounts } from "@/lib/content";

export const metadata: Metadata = { title: "Faculty" };

export default function FacultyIndex() {
  const faculty = getFaculty();
  const byArea = new Map<string, typeof faculty>();
  for (const f of faculty) byArea.set(f.area ?? "Other", [...(byArea.get(f.area ?? "Other") ?? []), f]);
  const areas = [...byArea.keys()].sort();

  return (
    <>
      <div className="crumbs"><Link href="/">Home</Link> / Faculty</div>
      <h1 style={{ fontSize: "1.8rem", marginBottom: ".3rem" }}>Faculty</h1>
      <p className="lead">{faculty.length} professors across {areas.length} areas.</p>
      {areas.map((area) => (
        <section key={area}>
          <div className="section">{area}</div>
          <div className="grid">
            {byArea.get(area)!.map((f) => {
              const papers = papersOf(f.slug);
              return (
                <div className="card" key={f.slug}>
                  <div className="prof-card">
                    <Avatar f={f} small />
                    <div>
                      <h3><Link href={`/faculty/${f.slug}`}>{f.name}</Link></h3>
                      <div className="meta">{f.title ?? f.area} · {papers.length} papers</div>
                      <Chips items={topicCounts(papers).slice(0, 3).map(([t]) => t)} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}
