// Validates content/*.json before every build so a typo in a hand-written summary can't break the site.
import fs from "node:fs";
import path from "node:path";

const root = path.join(process.cwd(), "content");
const errors = [];
const read = (dir) =>
  fs.readdirSync(path.join(root, dir)).filter((f) => f.endsWith(".json")).map((f) => {
    const file = `${dir}/${f}`;
    try {
      return { file, data: JSON.parse(fs.readFileSync(path.join(root, file), "utf8")) };
    } catch (e) {
      errors.push(`${file}: invalid JSON (${e.message})`);
      return null;
    }
  }).filter(Boolean);

const faculty = read("faculty");
const slugs = new Set();
for (const { file, data } of faculty) {
  for (const k of ["slug", "name"]) if (!data[k]) errors.push(`${file}: missing "${k}"`);
  if (data.slug && `${data.slug}.json` !== path.basename(file)) errors.push(`${file}: slug "${data.slug}" doesn't match file name`);
  slugs.add(data.slug);
}

const SUMMARY_FIELDS = ["oneLiner", "overview", "question", "method", "data", "findings", "whyItMatters", "topics", "basis", "source"];
const ids = new Set();
for (const { file, data } of read("papers")) {
  for (const k of ["id", "title", "isb", "authors"]) if (data[k] === undefined) errors.push(`${file}: missing "${k}"`);
  if (data.id && `${data.id}.json` !== path.basename(file)) errors.push(`${file}: id "${data.id}" doesn't match file name`);
  if (ids.has(data.id)) errors.push(`${file}: duplicate id ${data.id}`);
  ids.add(data.id);
  for (const s of data.isb ?? []) if (!slugs.has(s)) errors.push(`${file}: isb slug "${s}" has no content/faculty/${s}.json`);
  const s = data.summary;
  if (s) {
    for (const k of SUMMARY_FIELDS) if (s[k] === undefined) errors.push(`${file}: summary missing "${k}"`);
    if (!Array.isArray(s.findings) || !Array.isArray(s.topics)) errors.push(`${file}: findings/topics must be arrays`);
    if (!["full_text", "abstract_only", "published_sources"].includes(s.basis)) errors.push(`${file}: bad basis "${s.basis}"`);
    if (s.oneLiner && s.oneLiner.split(/\s+/).length > 30) errors.push(`${file}: oneLiner over 30 words`);
  }
}
for (const { file, data } of faculty) {
  for (const t of data.profile?.themes ?? []) for (const id of t.papers ?? []) if (!ids.has(id)) errors.push(`${file}: theme "${t.name}" cites unknown paper ${id}`);
}

if (errors.length) {
  console.error(`Content check failed (${errors.length}):\n- ` + errors.join("\n- "));
  process.exit(1);
}
console.log(`Content OK: ${faculty.length} faculty, ${ids.size} papers.`);
