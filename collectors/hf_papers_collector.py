"""Hugging Face Daily Papers — a community-curated paper aggregator.

Higher precision than trawling arXiv directly: papers here have been submitted
and upvoted by people, so an upvote threshold filters most noise for free, before
any classifier call. Ids are arXiv ids, so pipeline.canonical_url collapses these
onto the same key as the arXiv collector's entries.
"""
from datetime import datetime

import requests

from collectors import pipeline

API = "https://huggingface.co/api/daily_papers"


def _parse_date(value):
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


def collect_hf_papers(session, config):
    hf_config = config['sources'].get('hf_papers', {})
    if not hf_config.get('enabled'):
        return 0

    min_upvotes = hf_config.get('min_upvotes', 3)

    try:
        response = requests.get(
            API,
            params={"limit": hf_config.get('limit', 100)},
            timeout=30,
            headers={"User-Agent": "roofline-feed/1.0"},
        )
        response.raise_for_status()
        entries = response.json()
    except Exception as exc:
        print(f"    Error fetching HF daily papers: {exc}")
        return 0

    rows = []
    for entry in entries:
        paper = entry.get('paper') or {}
        paper_id = paper.get('id')
        if not paper_id:
            continue

        # The free pre-filter: community upvotes, no API call needed.
        if (paper.get('upvotes') or 0) < min_upvotes:
            continue

        # ai_keywords are HF's own topic labels — useful context for the
        # classifier, which still assigns our own taxonomy.
        keywords = ", ".join(paper.get('ai_keywords') or [])
        summary = paper.get('ai_summary') or paper.get('summary') or ''
        if keywords:
            summary = f"{summary}\n\nKeywords: {keywords}"

        rows.append({
            "title": paper.get('title') or entry.get('title') or '',
            "url": f"https://arxiv.org/abs/{paper_id}",
            "source": "hf:papers",
            "published_date": _parse_date(paper.get('publishedAt') or entry.get('publishedAt')),
            "summary": summary,
        })

    return pipeline.commit(session, config, rows)
