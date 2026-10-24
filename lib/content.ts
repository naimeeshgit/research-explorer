// Reads content/*.json at build time. Only imported by server components.
import fs from "node:fs";
import path from "node:path";
import type { Faculty, Paper } from "./types";

const ROOT = path.join(process.cwd(), "content");

function readDir<T>(dir: string): T[] {
  const full = path.join(ROOT, dir);
  if (!fs.existsSync(full)) return [];
  return fs
    .readdirSync(full)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(fs.readFileSync(path.join(full, f), "utf8")) as T);
}

let cache: { faculty: Faculty[]; papers: Paper[] } | null = null;

function load() {
  if (cache) return cache;
  const faculty = readDir<Faculty>("faculty").sort((a, b) => a.name.localeCompare(b.name));
  const slugs = new Set(faculty.map((f) => f.slug));
  const papers = readDir<Paper>("papers")
    .filter((p) => !p.hidden)
    .map((p) => ({ ...p, isb: p.isb.filter((s) => slugs.has(s)) }))
    .filter((p) => p.isb.length > 0);
  cache = { faculty, papers };
  return cache;
}

export const getFaculty = () => load().faculty;
export const getPapers = () => load().papers;
export const getFacultyBySlug = (slug: string) => load().faculty.find((f) => f.slug === slug);
export const getPaper = (id: string) => load().papers.find((p) => p.id === id);

export function newestFirst(papers: Paper[]): Paper[] {
  return [...papers].sort((a, b) => (b.date ?? String(b.year ?? "")).localeCompare(a.date ?? String(a.year ?? "")));
}

export function papersOf(slug: string): Paper[] {
  return newestFirst(load().papers.filter((p) => p.isb.includes(slug)));
}

/** Topic tags across papers, case variants merged under the first spelling seen. */
export function topicCounts(papers: Paper[]): [string, number][] {
  const shown = new Map<string, string>();
  const counts = new Map<string, number>();
  for (const p of papers) {
    for (const t of p.summary?.topics ?? []) {
      const key = t.toLowerCase().trim().replace(/\s+/g, " ");
      if (!shown.has(key)) shown.set(key, t.trim());
      const label = shown.get(key)!;
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function stats() {
  const { faculty, papers } = load();
  const summarised = papers.filter((p) => p.summary);
  return {
    faculty: faculty.length,
    papers: papers.length,
    summaries: summarised.length,
    fullText: summarised.filter((p) => p.summary!.basis === "full_text").length,
  };
}
