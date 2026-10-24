import type { MetadataRoute } from "next";
import { getFaculty, getPapers } from "@/lib/content";

export const dynamic = "force-static";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "http://localhost:3000");

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${BASE}/` },
    { url: `${BASE}/faculty` },
    { url: `${BASE}/about` },
    ...getFaculty().map((f) => ({ url: `${BASE}/faculty/${f.slug}` })),
    ...getPapers().map((p) => ({ url: `${BASE}/papers/${p.id}` })),
  ];
}
