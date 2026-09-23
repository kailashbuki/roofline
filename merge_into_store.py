"""Fold a saved articles.json into whatever the store currently holds.

Used by the workflow when a push races: after resetting onto the remote tip, the
run's own freshly collected rows are merged back in through store.hydrate/dump,
so hot/archive rotation is recomputed correctly rather than hand-patched.

Merging only the hot file would silently drop rows that aged into an archive
during the losing run.

    python merge_into_store.py /tmp/ours-articles.json
"""
import json
import os
import sys

from database import Article
from store import hydrate, dump, DATA_PATH, _from_iso


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: merge_into_store.py <saved-articles.json>")
    saved_path = sys.argv[1]

    session = hydrate()  # remote hot file + every remote archive
    existing = {url for (url,) in session.query(Article.url).all()}
    before = len(existing)

    added = 0
    if os.path.exists(saved_path):
        with open(saved_path, encoding="utf-8") as handle:
            for record in json.load(handle).get("articles", []):
                url = record.get("url")
                if not url or url in existing:
                    continue
                existing.add(url)
                session.add(Article(
                    title=record.get("title", ""),
                    url=url,
                    source=record.get("source", ""),
                    published_date=_from_iso(record.get("published_date")),
                    summary=record.get("summary", ""),
                    relevance_score=record.get("relevance_score", 0.0),
                    tags=record.get("tags", "") or "",
                    area=record.get("area") or "other",
                    importance=record.get("importance"),
                    why=record.get("why") or "",
                ))
                added += 1
        session.commit()

    total = dump(session, DATA_PATH)
    print(f"merge_into_store: {before} on remote + {added} from this run = {total} total")


if __name__ == "__main__":
    main()
