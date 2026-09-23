import requests

from datetime import datetime

from collectors import pipeline

TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


def collect_hackernews(session, config):
    hn_config = config['sources']['hackernews']
    if not hn_config['enabled']:
        return 0

    story_ids = requests.get(TOP_STORIES, timeout=30).json()[:hn_config['max_items']]

    # No keyword pre-filter: every story goes to the classifier, and anything it
    # rejects is remembered so we never pay to judge it twice.
    already_judged = pipeline.already_judged(session)

    rows = []
    for story_id in story_ids:
        fallback_url = f"https://news.ycombinator.com/item?id={story_id}"
        if fallback_url in already_judged:
            continue

        try:
            story = requests.get(ITEM.format(id=story_id), timeout=15).json()
        except Exception:
            continue

        if not story or story.get('type') != 'story':
            continue

        url = story.get('url') or fallback_url
        if url in already_judged:
            continue

        rows.append({
            "title": story.get('title', ''),
            "url": url,
            "source": "hackernews",
            "published_date": datetime.fromtimestamp(story.get('time', 0)),
            "summary": (story.get('text') or '')[:500],
        })

    return pipeline.commit(session, config, rows)
