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


def _enrich(row, record):
    """Fill any field the store is missing from the incoming record."""
    changed = False

    if row.importance is None and record.get("importance") is not None:
        row.importance = record["importance"]
        row.why = record.get("why") or row.why
        changed = True

    for field in ("area", "tags", "why", "summary"):
        incoming = record.get(field)
        current = getattr(row, field, None)
        # "other" is a placeholder area, not a real value, so it loses to anything.
        placeholder = not current or (field == "area" and current == "other")
        if incoming and placeholder and incoming != current:
            setattr(row, field, incoming)
            changed = True

    if row.first_seen is None and record.get("first_seen"):
        row.first_seen = _from_iso(record["first_seen"])
        changed = True

    return changed


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: merge_into_store.py <saved-articles.json>")
    saved_path = sys.argv[1]

    session = hydrate()  # remote hot file + every remote archive
    rows_by_url = {row.url: row for row in session.query(Article).all()}
    before = len(rows_by_url)

    added = 0
    enriched = 0
    if os.path.exists(saved_path):
        with open(saved_path, encoding="utf-8") as handle:
            for record in json.load(handle).get("articles", []):
                url = record.get("url")
                if not url:
                    continue

                row = rows_by_url.get(url)
                if row is not None:
                    # Adding missing URLs is not enough. A backfill improves rows the
                    # store already holds, and on a push race those improvements
                    # would be silently discarded — the run's whole work lost.
                    #
                    # Enriching field-by-field rather than naming a fixed list: the
                    # first version only carried importance across, which is exactly
                    # how a first_seen backfill got thrown away.
                    if _enrich(row, record):
                        enriched += 1
                    continue

                row = Article(
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
                    first_seen=_from_iso(record.get("first_seen")),
                )
                rows_by_url[url] = row
                session.add(row)
                added += 1
        session.commit()

    total = dump(session, DATA_PATH)
    print(f"merge_into_store: {before} in store + {added} new + {enriched} enriched "
          f"= {total} total")


if __name__ == "__main__":
    main()
