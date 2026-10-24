# ISB Research Explorer

Search ISB faculty research by topic, read plain-English summaries of their papers, and see
which professors to talk to about what.

It's a static Next.js site: every page is built from the JSON files in `content/`. There's
no database, server or API key at runtime, so it deploys to Vercel's free tier as is.

## Run it locally

Needs Node 20.9+.

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # checks content/, then builds every page
```

## Deploy to Vercel

1. Push this folder to a GitHub repo.
2. On vercel.com: **Add New → Project → Import** that repo. Vercel detects Next.js; keep
   every default (no environment variables needed) and click **Deploy**.
3. Every push to `main` redeploys. Pull requests get preview URLs.

Optional: set `NEXT_PUBLIC_SITE_URL` (e.g. `https://isb-research.vercel.app`) so the
sitemap uses your custom domain.

CLI alternative: `npx vercel` (first time, to link), then `npx vercel --prod`.

## Layout

| Path | What it is |
|---|---|
| `content/faculty/<slug>.json` | One file per professor: name, area, title, homepage, research profile |
| `content/papers/<OpenAlex id>.json` | One file per paper: metadata, ISB authors, summary, other versions |
| `app/` | Pages: home + search, `/faculty`, `/faculty/[slug]`, `/papers/[id]`, `/about` |
| `components/` | Search (MiniSearch, runs in the browser), paper list, shared UI |
| `scripts/check-content.mjs` | Validates `content/` before each build |
| `python/` | The original data pipeline (OpenAlex fetch, PDF download). Not deployed. |

How to write or edit summaries and profiles: **[CONTENT_GUIDE.md](CONTENT_GUIDE.md)**.

## Refreshing data from the Python pipeline

`python/` still fetches faculty and paper metadata from OpenAlex into `python/data/explorer.db`.
To turn that database into content files:

```bash
python3 python/scripts/export_content.py          # adds new papers/faculty, leaves existing files alone
python3 python/scripts/export_content.py --force  # also refreshes metadata of existing files
```

Files with a hand-written summary (`source.kind: "claude-research"`) or `"locked": true` are
never overwritten.
