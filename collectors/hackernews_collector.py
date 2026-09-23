"""HackerNews via the Algolia search API, one targeted query at a time.

This replaces scanning the top-100, which was mostly off-topic and missed
anything that never reached the front page. Searching by title with typo
tolerance off gives high precision — "sglang" returns SGLang threads, not
articles that merely rhyme with it — and reaches the long tail.
"""
from datetime import datetime

import requests

from collectors import pipeline

SEARCH = "https://hn.algolia.com/api/v1/search_by_date"


def collect_hackernews(session, config):
    hn_config = config['sources']['hackernews']
    if not hn_config['enabled']:
        return 0

    per_query = hn_config.get('per_query', 20)
    min_points = hn_config.get('min_points', 0)

    rows = []
    seen = set()
    for query in hn_config['queries']:
        try:
            response = requests.get(
                SEARCH,
                params={
                    "query": query,
                    "tags": "story",
                    # Title-only, no typo tolerance: precision over recall.
                    "restrictSearchableAttributes": "title",
                    "typoTolerance": "false",
                    "hitsPerPage": per_query,
                },
                timeout=30,
            )
            response.raise_for_status()
            hits = response.json().get('hits', [])
        except Exception as exc:
            print(f"    Error searching HN for {query!r}: {exc}")
            continue

        for hit in hits:
            object_id = hit.get('objectID')
            if not object_id or object_id in seen:
                continue
            if (hit.get('points') or 0) < min_points:
                continue
            seen.add(object_id)

            try:
                published = datetime.fromisoformat(
                    hit['created_at'].replace('Z', '+00:00')
                ).replace(tzinfo=None)
            except (KeyError, ValueError):
                published = datetime.utcnow()

            rows.append({
                "title": hit.get('title') or '',
                "url": hit.get('url') or f"https://news.ycombinator.com/item?id={object_id}",
                "source": "hackernews",
                "published_date": published,
                "summary": f"{hit.get('points', 0)} points, "
                           f"{hit.get('num_comments', 0)} comments on HackerNews",
            })

    return pipeline.commit(session, config, rows)
