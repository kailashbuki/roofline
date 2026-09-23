# Inference News

Daily aggregation of LLM inference optimization research and engineering writing,
published as a static site.

**Live:** https://kailashbuki.github.io/inference-news/

## How it works

There is no server. GitHub Actions runs the collectors on a schedule, commits the
results as JSON, and deploys a static page that reads that JSON in the browser.

```
GitHub Actions (cron 3x/day)
  └─ collect_all.py
       ├─ hydrate in-memory SQLite from data/articles.json
       ├─ run 5 collectors (dedup by URL)
       ├─ score/tag new items via classifier.py (Gemini, keyword fallback)
       └─ dump back to data/articles.json
  └─ commit data/articles.json
  └─ deploy site/ + data/ to GitHub Pages
```

`data/articles.json` is the source of truth: diffable in git, and served to the
page as-is. SQLite exists only in memory for the duration of a run, which is what
lets the collectors keep their SQLAlchemy session interface unchanged.

## Components

- `collect_all.py` — runs every collector, hydrates and dumps the store
- `store.py` — `data/articles.json` ⇄ ephemeral in-memory SQLite
- `classifier.py` — relevance scoring and tagging via the Gemini API
- `relevance_scorer.py` — keyword scoring, used when Gemini is unavailable
- `database.py` — the `Article` model and config loader
- `collectors/` — arXiv, HackerNews, RSS (9 feeds), Anthropic blogs, AI Realist
- `site/` — the static page (plain HTML/CSS/JS, no build step)
- `.github/workflows/collect.yml` — collect, commit, deploy

## Local development

```bash
pip install -r requirements.txt
python collect_all.py          # updates data/articles.json

# serve the site the way Pages does, under a subpath
mkdir -p /tmp/pagesroot/inference-news
cp -r site/. /tmp/pagesroot/inference-news/
mkdir -p /tmp/pagesroot/inference-news/data
cp data/articles.json /tmp/pagesroot/inference-news/data/
(cd /tmp/pagesroot && python3 -m http.server 8899)
# → http://localhost:8899/inference-news/
```

Asset paths are relative, so the page works from any subpath without a base-URL
config.

## Configuration

`config.yaml` controls sources, feeds, keywords, and the minimum relevance score.

`classifier.py` reads these from the environment:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key. Absent ⇒ keyword scoring. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model id. |
| `GEMINI_API` | `generatecontent` | `generatecontent` or `interactions` (`/v1beta/interactions`). |
| `GEMINI_MIN_INTERVAL` | `4.5` | Seconds between calls. Free-tier limits are per-project now; see aistudio.google.com/rate-limit. |
| `GEMINI_MAX_CALLS` | `400` | Per-run ceiling so a backfill cannot exhaust the daily quota. |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Gemini 3 thinks by default and thought tokens count against this; too low truncates the JSON. |

Model ids and API surfaces move fast — `gemini-2.0-flash` was retired before
this shipped. Run `python verify_gemini.py` with `GEMINI_API_KEY` exported to
probe what your key can actually use; it prints the env values to paste into the
workflow. Verified 2026-09-23:

| Surface | Working models |
|---|---|
| `generatecontent` | `gemini-3.5-flash-lite` (schema enforced; least 503-prone) |
| `interactions` (`/v1beta`) | `gemini-3.6-flash`, `gemini-3.8-flash` |

The larger models frequently return `503 high demand` on the free tier, which is
why flash-lite is the default. Transient 5xx is retried three times with
exponential backoff before falling back to keyword scoring.

The API key is stored as a **GitHub Actions repository secret** and only ever
exists in the runner's environment. Classification happens at build time, so the
key never reaches a visitor's browser, and it is passed to the step via `env:`
rather than interpolated into a shell command. Never put it in `config.yaml`,
which is committed.

## Read state

Read/unread is kept in `localStorage`, so it is per-browser and not synced. Note
that `kailashbuki.github.io` is a single origin shared with the personal
homepage, so the keys are namespaced `inference-news:*`.

## History

This started as a PyQt5 macOS widget; see `kiro-history.txt`. The widget was
retired in favour of this static site.
