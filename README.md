# roofline

A daily feed on the full AI performance stack — model architecture and
algorithms, training, post-training, inference optimization, serving systems,
and AI chips — published as a static site.

**Live:** https://kailashbuki.github.io/roofline/

Named for the [roofline model](https://en.wikipedia.org/wiki/Roofline_model),
which is the one abstraction that spans this whole scope: arithmetic intensity
on one axis, peak compute and memory bandwidth on the other.

## How it works

There is no server. GitHub Actions runs the collectors on a schedule, commits the
results as JSON, and deploys a static page that reads that JSON in the browser.

```
GitHub Actions (cron 3x/day)
  └─ collect_all.py
       ├─ hydrate in-memory SQLite from data/articles.json
       ├─ run 5 collectors, gathering candidates
       ├─ drop URLs already stored or already rejected
       ├─ batch-classify the rest via classifier.py (Gemini, keyword fallback)
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
- `classifier.py` — batched relevance scoring and tagging via the Gemini API
- `collectors/pipeline.py` — shared candidate → classify → store path
- `relevance_scorer.py` — keyword scoring, used when Gemini is unavailable
- `database.py` — the `Article` model and config loader
- `collectors/` — arXiv, HackerNews, RSS (9 feeds), Anthropic blogs, AI Realist
- `site/index.html` — the feed
- `site/pulse.html` — the trend dashboard (hand-rolled inline SVG, no chart library)
- `.github/workflows/collect.yml` — collect, commit, deploy

## Local development

```bash
pip install -r requirements.txt
python collect_all.py          # updates data/articles.json

# serve the site the way Pages does, under a subpath
mkdir -p /tmp/pagesroot/roofline
cp -r site/. /tmp/pagesroot/roofline/
mkdir -p /tmp/pagesroot/roofline/data
cp data/articles.json /tmp/pagesroot/roofline/data/
(cd /tmp/pagesroot && python3 -m http.server 8899)
# → http://localhost:8899/roofline/
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
| `GEMINI_MIN_INTERVAL` | `2.0` | Seconds between calls. Free-tier limits are per-project now; see aistudio.google.com/rate-limit. |
| `GEMINI_MAX_CALLS` | `60` | Per-run ceiling on *requests*, not articles. |
| `GEMINI_BATCH_SIZE` | `20` | Articles per request. |
| `GEMINI_BASE_OUTPUT_TOKENS` | `2048` | Output budget, plus 120/article. Gemini 3 thinks by default and thought tokens count against it; too low truncates the JSON. |

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

## The pulse dashboard

`pulse.html` is the "what changed" view, for catching up fast:

- **KPI tiles** — new today / 7d / 30d, unread, active sources. Headline numbers
  are stat tiles, not one-bar charts.
- **Volume per week** — 26 weeks, single series, crosshair tooltip.
- **Topic momentum** — the one to read first. Share of the last 7 days minus share
  of the prior three weeks, in percentage points. Deliberately *not* percent
  change: that divides by a baseline which is often zero, collapsing "appeared
  from nothing" and "doubled" into the same +100%. Topics with no prior activity
  are flagged `new` instead.
- **Topics over time** — small multiples, one panel per topic. Identity comes from
  the panel label, so all twelve sparklines share one hue instead of needing
  twelve colors.
- **Where it comes from** — source mix, one hue (never a value-ramp over nominal
  categories).
- **Highest signal, last 7 days** — top-scored unread items.

Every chart has a table view, one filter row scopes all of them, and light and
dark are two separately-chosen palettes rather than an automatic flip. The two
chart hues were validated against both surfaces with the dataviz validator:
dark `#1c1c1e` passes all six checks; light `#f2f2f7` passes with a contrast
warning on orange, relieved by the direct labels and table views.

## Why there is no keyword filtering

Relevance is decided by the model, not by keyword matching. Keywords in
`config.yaml` only constrain what the upstream APIs *return* — arXiv needs some
query, and its terms are deliberately broad so architecture and training papers
surface at all. `relevance_scorer.py` still exists, but only as the fallback for
when Gemini is unavailable.

Sending every candidate to a model is affordable because of three things:

1. **Batching.** One request carries `GEMINI_BATCH_SIZE` (default 20) articles
   and returns one verdict each, keyed by an echoed id. A run that would need
   ~330 single calls needs ~17.
2. **Dedup before classify.** URLs already in the store are never re-sent.
3. **A rejection ledger.** `data/rejected.json` remembers what the model turned
   down, so the ~90 off-topic stories in any HackerNews top-100 are judged once
   rather than three times a day forever. Only *model* rejections are recorded —
   a keyword-scored rejection is a guess made while the API was unavailable, and
   recording it would permanently block a real verdict later.

Feeds where everything is on topic set `filter: false` in `config.yaml`: they are
still classified, to get tags, but are never dropped on score.

## Read state

Read/unread is kept in `localStorage`, so it is per-browser and not synced. Note
that `kailashbuki.github.io` is a single origin shared with the personal
homepage, so the keys are namespaced `roofline:*`.

## History

This started as a PyQt5 macOS widget called Inference News; see
`kiro-history.txt`. The widget was retired in favour of this static site, and the
scope widened from inference-only to the whole stack.
