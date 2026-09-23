from datetime import datetime

import feedparser

from collectors import pipeline

FEED_URL = 'https://www.airealist.ai/feed'


def collect_airealist(session, config):
    """AI Realist (Julien Simon's Substack). Wholly on-topic, so nothing is
    dropped on score, but entries are still classified to get tags."""
    try:
        feed = feedparser.parse(FEED_URL)
    except Exception as exc:
        print(f"    Error collecting AI Realist: {exc}")
        return 0

    rows = []
    for entry in feed.entries:
        url = entry.get('link', '')
        if not url:
            continue

        published = entry.get('published_parsed')
        rows.append({
            "title": entry.get('title', 'No title'),
            "url": url,
            "source": "airealist",
            "published_date": datetime(*published[:6]) if published else datetime.utcnow(),
            "summary": entry.get('summary', '')[:1000],
        })

    return pipeline.commit(session, config, rows, always_keep=True)
