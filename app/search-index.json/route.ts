// Built once at build time into a static JSON file that the search box downloads.
import { getFaculty, getPapers } from "@/lib/content";
import type { SearchDoc } from "@/lib/types";

export const dynamic = "force-static";

export function GET() {
  const docs: SearchDoc[] = getPapers().map((p) => ({
    id: p.id,
    kind: "paper",
    title: p.title,
    year: p.year,
    venue: p.venue,
    isb: p.isb,
    oneLiner: p.summary?.oneLiner ?? "",
    overview: p.summary ? [p.summary.overview, p.summary.question, p.summary.findings.join(" ")].join(" ") : "",
    topics: (p.summary?.topics ?? []).join(" · "),
    abstract: p.summary ? "" : (p.abstract ?? ""),
    basis: p.summary?.basis ?? null,
  }));
  return Response.json(docs);
}
