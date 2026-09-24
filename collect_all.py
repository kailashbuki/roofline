import os
from datetime import datetime

from database import load_config, Article
from store import hydrate, dump, DATA_PATH
from classifier import classify_many
from collectors import pipeline
from collectors.arxiv_collector import collect_arxiv
from collectors.hf_papers_collector import collect_hf_papers
from collectors.hackernews_collector import collect_hackernews
from collectors.rss_collector import collect_rss
from collectors.anthropic_scraper import collect_anthropic
from collectors.airealist_collector import collect_airealist

COLLECTORS = [
    ("arXiv", collect_arxiv),
    ("HF Daily Papers", collect_hf_papers),
    ("HackerNews", collect_hackernews),
    ("RSS Feeds", collect_rss),
    ("Anthropic", collect_anthropic),
    ("AI Realist", collect_airealist),
]


# Cap so a large backlog is worked through over several runs rather than blowing
# the quota in one.
RETRY_LIMIT = int(os.environ.get("ROOFLINE_RETRY_LIMIT", "200"))


def retry_unrated(session, config):
    """Re-judge rows the model never successfully rated.

    Without this a single rate-limited run leaves its articles unrated for ever,
    because classification otherwise only ever runs on newly seen URLs — and the
    only signal was a notice on the page asking a human to go and fix it.
    """
    rows = (session.query(Article)
            .filter(Article.importance.is_(None))
            .order_by(Article.published_date.desc())
            .limit(RETRY_LIMIT)
            .all())
    if not rows:
        return 0

    verdicts = classify_many([(row.title, row.summary or "") for row in rows])
    fixed = 0
    for row, (verdict, judged_by) in zip(rows, verdicts):
        if judged_by != "gemini":
            continue
        # 0.0 rather than None: a rejection is a verdict, and leaving None here
        # would queue the same row for retry on every future run.
        row.importance = 0.0 if verdict.importance is None else verdict.importance
        row.relevance_score = verdict.score
        row.why = verdict.why
        row.area = verdict.area or row.area
        if verdict.tags:
            row.tags = verdict.tags
        fixed += 1

    session.commit()
    return fixed


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

    unrated_before = session.query(Article).filter(Article.importance.is_(None)).count()
    if unrated_before:
        fixed = retry_unrated(session, config)
        print(f"  Retried unrated: {fixed} of {unrated_before} now classified")

    stored = dump(session, DATA_PATH)
    rejected = pipeline.save_rejected()
    print(f"Total: {total} new articles ({stored} in store, {rejected} rejected urls remembered)")
    print(f"Gemini requests this run: {pipeline.classify_calls()}\n")
    return total


if __name__ == "__main__":
    run_collection()
