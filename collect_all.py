from datetime import datetime

from database import load_config
from store import hydrate, dump, DATA_PATH
from collectors import pipeline
from collectors.arxiv_collector import collect_arxiv
from collectors.hackernews_collector import collect_hackernews
from collectors.rss_collector import collect_rss
from collectors.anthropic_scraper import collect_anthropic
from collectors.airealist_collector import collect_airealist

COLLECTORS = [
    ("arXiv", collect_arxiv),
    ("HackerNews", collect_hackernews),
    ("RSS Feeds", collect_rss),
    ("Anthropic", collect_anthropic),
    ("AI Realist", collect_airealist),
]


def run_collection():
    config = load_config()
    session = hydrate(DATA_PATH)
    pipeline.load_rejected()

    print(f"[{datetime.now()}] Starting collection...")

    total = 0
    for name, collector in COLLECTORS:
        try:
            count = collector(session, config)
            print(f"  {name}: {count} new articles")
            total += count
        except Exception as exc:
            # One broken feed must not cost us the whole run.
            print(f"  {name}: FAILED ({type(exc).__name__}: {exc})")

    stored = dump(session, DATA_PATH)
    rejected = pipeline.save_rejected()
    print(f"Total: {total} new articles ({stored} in store, {rejected} rejected urls remembered)")
    print(f"Gemini requests this run: {pipeline.classify_calls()}\n")
    return total


if __name__ == "__main__":
    run_collection()
