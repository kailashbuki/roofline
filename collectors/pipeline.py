"""Shared candidate → verdict → store path for every collector.

Collectors gather candidates and hand them here. This module is what keeps the
Gemini bill down:

  1. URLs already stored, already rejected, or duplicated inside the batch are
     dropped before any API call.
  2. Survivors are classified in batches (see classifier.classify_many).
  3. Rejections are remembered in data/rejected.json, so the ~90 off-topic
     HackerNews stories in any given top-100 are judged once, not three times a
     day forever.

Feeds that should bypass relevance filtering entirely (a blog where everything
is on-topic) pass always_keep=True: they still get tagged, but are never dropped
on score.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import classifier
from classifier import classify_many
from database import Article

REJECTED_PATH = os.path.join("data", "rejected.json")
# Plenty for years of HackerNews churn while keeping the file small.
REJECTED_CAP = 8000

_rejected = set()
_order = []

# 2509.12345 / 2509.12345v3 / math.GT/0309136 style arXiv ids
_ARXIV_ABS = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>[^?#]+?)(?:v\d+)?(?:\.pdf)?/?$", re.I)
_HF_PAPER = re.compile(r"huggingface\.co/papers/(?P<id>[^?#/]+)", re.I)


def canonical_url(url):
    """Collapse the many spellings of one article into a single key.

    The same paper arrives as an arXiv abs link, an arXiv pdf link, a versioned
    entry_id from the arXiv API, and a huggingface.co/papers link. Without this
    they would all be stored as separate articles.
    """
    if not url:
        return url

    for pattern in (_ARXIV_ABS, _HF_PAPER):
        match = pattern.search(url)
        if match:
            return f"https://arxiv.org/abs/{match.group('id')}"

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if not parts.scheme:
        return url

    # Drop campaign junk so the same link shared twice is one article.
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "ref_")) and k.lower() not in {"ref", "source"}
    ])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def load_rejected(path=REJECTED_PATH):
    """Load the rejection ledger. Call once at the start of a run."""
    global _rejected, _order
    _rejected, _order = set(), []
    if not os.path.exists(path):
        return _rejected
    try:
        with open(path, "r", encoding="utf-8") as handle:
            urls = json.load(handle).get("urls", [])
    except (json.JSONDecodeError, OSError):
        return _rejected
    _order = list(dict.fromkeys(urls))
    _rejected = set(_order)
    return _rejected


def save_rejected(path=REJECTED_PATH):
    """Persist the ledger, oldest entries pruned first."""
    trimmed = _order[-REJECTED_CAP:]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"count": len(trimmed), "urls": trimmed}, handle, indent=1)
        handle.write("\n")
    return len(trimmed)


def _reject(url):
    if url not in _rejected:
        _rejected.add(url)
        _order.append(url)


def classify_calls():
    """How many Gemini requests this run has made, for the run summary."""
    return classifier._state["calls"]


def already_judged(session):
    """URLs we have either stored or rejected — no need to fetch or classify."""
    return {url for (url,) in session.query(Article.url).all()} | _rejected


def new_candidates(session, rows):
    """Drop rows we have already stored, already rejected, or seen twice here."""
    stored = {url for (url,) in session.query(Article.url).all()}
    fresh, seen_here = [], set()

    for row in rows:
        url = canonical_url(row.get("url"))
        if not url or url in stored or url in _rejected or url in seen_here:
            continue
        row["url"] = url
        seen_here.add(url)
        fresh.append(row)

    return fresh


def pick_area(candidate, verdict):
    """Reconcile a source-derived area hint with the model's choice.

    The hint wins for HackerNews, where the search query that surfaced a story is
    better evidence than a bare title with no abstract. Elsewhere the hint only
    fills in when the model declined to commit, so a pinned feed that publishes
    something off its usual beat still lands in the right section.
    """
    hint = candidate.get("area_hint")
    if not hint:
        return verdict.area
    if candidate.get("source", "").startswith("hackernews"):
        return hint
    return hint if verdict.area == "other" else verdict.area


def commit(session, config, rows, always_keep=False):
    """Classify new candidates and store the ones that pass. Returns count kept."""
    candidates = new_candidates(session, rows)
    if not candidates:
        return 0

    verdicts = classify_many([(c["title"], c.get("summary", "")) for c in candidates])
    min_score = config.get("relevance", {}).get("min_score", 0.4)

    kept = 0
    keepers = []
    for candidate, (verdict, judged_by) in zip(candidates, verdicts):
        keep_regardless = candidate.get("always_keep", always_keep)
        if not keep_regardless and verdict.score < min_score:
            # Only a real model verdict is final. A keyword-scored rejection is
            # a guess made because Gemini was unavailable, so leave the URL
            # unrecorded and let a later run judge it properly.
            if judged_by == "gemini":
                _reject(candidate["url"])
            continue

        keepers.append(Article(
            title=(candidate["title"] or "")[:500],
            url=candidate["url"],
            source=candidate["source"],
            published_date=candidate.get("published_date"),
            summary=(candidate.get("summary") or "")[:1000],
            relevance_score=verdict.score,
            tags=verdict.tags,
            area=pick_area(candidate, verdict),
            importance=verdict.importance,
            why=verdict.why,
            first_seen=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        kept += 1

    for article in keepers:
        session.add(article)
    session.commit()
    return kept
