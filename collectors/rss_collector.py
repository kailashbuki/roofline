import time
from datetime import datetime

import feedparser

from collectors import pipeline


def collect_rss(session, config):
    rss_config = config['sources']['rss_feeds']
    if not rss_config['enabled']:
        return 0

    count = 0
    for feed_info in rss_config['feeds']:
        # Feeds marked filter: false are wholly on-topic, so nothing is dropped
        # on score — but they are still classified, to get tags.
        always_keep = not feed_info.get('filter', True)

        try:
            feed = feedparser.parse(feed_info['url'])
            rows = []

            for entry in feed.entries[:feed_info.get('max_items', 20)]:
                url = entry.get('link', '')
                if not url:
                    continue

                published = entry.get('published_parsed') or entry.get('updated_parsed')
                rows.append({
                    "title": entry.get('title', ''),
                    "url": url,
                    "source": f"rss:{feed_info['name']}",
                    "published_date": datetime(*published[:6]) if published else datetime.utcnow(),
                    "summary": entry.get('summary', entry.get('description', ''))[:1000],
                })

            count += pipeline.commit(session, config, rows, always_keep=always_keep)
            time.sleep(1)  # be polite to the feed hosts
        except Exception as exc:
            print(f"    Error fetching {feed_info['name']}: {exc}")

    return count
