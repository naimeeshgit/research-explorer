// Shapes of the JSON files in content/. See CONTENT_GUIDE.md for how to write them.

export type SummarySource =
  | { kind: "ai-pipeline"; model: string; prompt: string; createdAt: string }
  | { kind: "claude-research"; createdAt: string; sources: string[] }
  | { kind: "faculty"; createdAt: string; note?: string };

export interface Summary {
  oneLiner: string;
  overview: string;
  question: string;
  method: string;
  data: string;
  findings: string[];
  whyItMatters: string;
  topics: string[];
  industries?: string[];
  geographies?: string[];
  basis: "full_text" | "abstract_only" | "published_sources";
  source: SummarySource;
}

export interface Author {
  name: string;
  isb?: string; // faculty slug when the author is ISB faculty in this site
}

export interface Version {
  id: string;
  type: string | null;
  venue: string | null;
  year: number | null;
  url: string | null;
}

export interface Paper {
  id: string; // OpenAlex work ID, e.g. W2118977847
  title: string;
  year: number | null;
  date: string | null;
  type: string | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  pdf: string | null;
  citations: number;
  authors: Author[];
  isb: string[];
  abstract: string | null;
  summary: Summary | null;
  versions: Version[];
  hidden?: boolean;
}

export interface Theme {
  name: string;
  description: string;
  papers: string[]; // paper IDs
}

export interface Profile {
  summary: string;
  themes: Theme[];
  talkTo: string[]; // "good to talk to about"
  sources: string[];
  createdAt: string;
}

export interface Faculty {
  slug: string;
  name: string;
  title: string | null;
  area: string | null;
  homepage: string | null;
  openalex: string[];
  photo: string | null;
  profile: Profile | null;
}

export interface SearchDoc {
  id: string;
  kind: "paper" | "faculty";
  title: string;
  year?: number | null;
  venue?: string | null;
  isb?: string[];
  oneLiner?: string;
  overview?: string;
  topics?: string;
  abstract?: string;
  basis?: string | null;
  area?: string | null;
}
