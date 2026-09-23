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
       ├─ batch-classify the rest: relevance, area, importance, why, tags
       └─ dump back to data/articles.json
  └─ commit data/articles.json
  └─ deploy site/ + data/ to GitHub Pages
```

`data/articles.json` is the source of truth: diffable in git, and served to the
page as-is. SQLite exists only in memory for the duration of a run, which is what
lets the collectors keep their SQLAlchemy session interface unchanged.

### What is actually stored, and why the repo does not blow up

A job that rewrites one growing file three times a day is a repo-size problem, so
the stored record is kept to what the page renders:

| Field | Stored | Note |
|---|---|---|
| `title`, `url`, `source`, `published_date` | always | |
| `area` | always | one of `classifier.AREAS`; the section the item appears under |
| `importance`, `why` | once rated | absent means never seen by the model |
| `tags` | always | sub-topic chips |
| `summary` | **only while unrated** | it is an input to classification, never rendered — and it was 55% of the file |
| `relevance_score` | no | superseded by `importance` |

Two mechanisms keep it flat rather than growing:

1. **Summaries are dropped once a row is rated.** 691 → 443 bytes per row.
2. **A rolling hot window plus monthly archives.** `data/articles.json` holds only
   the last `ROOFLINE_HOT_DAYS` (120) days — that is all the page can display —
   and older rows move to `data/archive/YYYY-MM.json`, rewritten only when that
   month's contents change. So the file the job rewrites three times a day is
   bounded at roughly 3 MB in steady state no matter how many years accumulate,
   and the archives are near-static in git. Only the hot file is published to
   Pages, so the page load stays small too.

`store.hydrate()` reads the hot file *and* every archive, so dedup and the
rejection ledger still see the entire history.

## Components

- `collect_all.py` — runs every collector, hydrates and dumps the store
- `store.py` — `data/articles.json` ⇄ ephemeral in-memory SQLite
- `classifier.py` — batched relevance scoring and tagging via the Gemini API
- `collectors/pipeline.py` — shared candidate → classify → store path
- `relevance_scorer.py` — keyword scoring, used when Gemini is unavailable
- `database.py` — the `Article` model and config loader
- `collectors/` — arXiv, HackerNews, RSS (9 feeds), Anthropic blogs, AI Realist
- `site/index.html` — the briefing (plain HTML/CSS/JS, no build step)
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
The areas and the importance rubric live in `classifier.py` (`AREAS`,
`build_prompt`).

Importance is judged on novelty of problem formulation, creativity of
methodology, surprisingness of results, potential impact, and departure from
existing approaches — one call per batch, alongside relevance and area, so the
editorial judgement costs no extra requests.

### Backfilling and pushing: use ./sync.sh

The scheduled workflow commits to `main` three times a day, so a plain
`git push` after a local backfill loses the race whenever the timing is unlucky —
and a naive resolution silently discards one side's work. `./sync.sh` does the
whole loop safely:

```bash
export GEMINI_API_KEY='...'
./sync.sh              # classify unrated rows, then merge + push
./sync.sh --digest     # also rebuild the per-area digest
./sync.sh --push-only  # just merge + push
```

It merges by re-deriving through the store (`merge_into_store.py`), which both
*adds* rows only the remote has and *enriches* rows whose ratings only you have.
That second half matters: a merge that only appends URLs would throw away every
rating a backfill just produced.

To preview without writing anything: `python reclassify.py --dry-run`.

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

## One page, organised by what to read

**Area pills** across the top switch fronts in one click (keys `0`-`6`), each
showing its item count and how many arrived since your last visit — so "where did
things happen?" is answerable without scrolling. Selecting a single front shows
its **digest**: one or two sentences on the state of play there, synthesised by
`build_digest.py` from that area's highest-importance items (~6 requests per run,
written to `data/digest.json`, treated as optional by the page).

The site is a **briefing**, not a feed and not a dashboard. It answers one
question — what must I read? — and deliberately shows no volume charts, topic
momentum, or source counts: those describe the pipeline, not the news.

- **Start here** — the five highest-importance items across every area.
- **Then one section per area of interest**, in fixed order: model architecture,
  new models, inference optimization, inference engines & serving, silicon,
  training & post-training, everything else. Six per area, expandable.
- **Every item carries a one-line justification** of what is actually new and why
  it matters. That line is the point: it lets you skip without opening.
- **An importance bar** ("only what matters" / "worth a look" / "everything")
  rather than a sort order, because the question is what to *read*, not how to
  rank.
- **"Since last visit" as the default range**, which is the axis a daily briefing
  needs; a fixed day count is only a proxy for it. The visit mark advances after
  render, so the current visit's new items stay visible while you read them.
- **"Everything else" is collapsed and never supplies the lede.** It is where
  unclassified and off-beat items land, so letting it into the headline slot would
  fill it with noise.
- **A notice when a large share of rows are unclassified**, naming the count and
  what to run. Without area and importance the page degrades to a flat list, and
  it should say so rather than look broken.

Items the model has never seen show `–` instead of a number, and are never hidden
by the importance bar — an unrated row could not have cleared a bar it was never
measured against.

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

### How the area is decided

For **papers** the title and abstract are the only inputs — the abstract is
truncated to `GEMINI_SUMMARY_CHARS` (400) before sending, since more text costs
tokens without improving the judgement.

For **feeds whose beat is unambiguous**, `config.yaml` pins the area outright
(`area: silicon` on SemiAnalysis and Chips and Cheese, `inference-engines` on the
vLLM blog, `training` on Interconnects). A pin only fills in when the model
declines to commit, so a pinned feed publishing off its usual beat still lands
correctly.

**HackerNews** is the tricky case: a bare title, no abstract. The trick is that
the *query which surfaced the story* is itself strong evidence — so queries are
grouped by area in `config.yaml`, and a hit inherits its group's area. A story
found by searching `hbm` or `nvlink` is silicon; one found by `vllm` or `sglang`
is an inference engine. There the hint overrides the model rather than deferring
to it.

## Read state

Read/unread is kept in `localStorage`, so it is per-browser and not synced. Note
that `kailashbuki.github.io` is a single origin shared with the personal
homepage, so the keys are namespaced `roofline:*`.

## History

This started as a PyQt5 macOS widget called Inference News; see
`kiro-history.txt`. The widget was retired in favour of this static site, and the
scope widened from inference-only to the whole stack.
