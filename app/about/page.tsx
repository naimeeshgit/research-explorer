import type { Metadata } from "next";
import { stats } from "@/lib/content";

export const metadata: Metadata = { title: "About" };

export default function About() {
  const s = stats();
  return (
    <div className="prose">
      <h1 style={{ fontSize: "1.8rem", marginBottom: ".5rem" }}>About this project</h1>
      <p className="lead">
        ISB Research Explorer helps students find which professors work on a topic, understand their papers in plain
        English, and walk into office hours with better questions. It covers {s.faculty} professors and {s.papers} papers
        so far.
      </p>
      <h2>Where the data comes from</h2>
      <p>
        Paper metadata (titles, co-authors, venues, citation counts) comes from OpenAlex, an open index of scholarly work.
        Journal, SSRN and working-paper copies of the same paper are merged into one entry.
      </p>
      <h2>How summaries are written</h2>
      <p>
        Each summary is written from the paper itself where an open copy exists, otherwise from its abstract and public
        sources such as the journal page, the author&apos;s site and SSRN. Every paper page says which basis was used and
        links to the original. Summaries keep the authors&apos; own hedges and never claim more than the paper does.
      </p>
      <h2>Corrections</h2>
      <p>
        If you are a faculty member and something here is wrong or missing, please get in touch and it will be fixed.
      </p>
      <p className="small">This is an independent student project and is not affiliated with or endorsed by ISB.</p>
    </div>
  );
}
