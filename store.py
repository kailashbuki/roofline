"""JSON-backed article store.

data/articles.json is the durable source of truth: diffable in git and served
directly to the static site. SQLite is ephemeral scratch that exists only for
the duration of a collection run, which is what lets the collectors keep using
the SQLAlchemy session interface unchanged.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Article, Base

DATA_PATH = os.path.join("data", "articles.json")
ARCHIVE_DIR = os.path.join("data", "archive")
# The hot file holds only what the page can show. Older rows move to monthly
# archives, which stops a 3x/day job from rewriting years of history every run.
HOT_DAYS = int(os.environ.get("ROOFLINE_HOT_DAYS", "120"))


def _to_iso(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return value.isoformat(timespec="seconds")


def _from_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, AttributeError):
        return None


def read_json(path=DATA_PATH):
    """Return the list of article dicts, or [] if the file does not exist."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("articles", [])


def archive_files():
    if not os.path.isdir(ARCHIVE_DIR):
        return []
    return sorted(os.path.join(ARCHIVE_DIR, f)
                  for f in os.listdir(ARCHIVE_DIR) if f.endswith(".json"))


def read_all(path=DATA_PATH):
    """Hot file plus every archive — dedup must see the whole history."""
    rows = list(read_json(path))
    for archive in archive_files():
        rows.extend(read_json(archive))
    return rows


def hydrate(path=DATA_PATH):
    """Build an in-memory SQLite session preloaded from the JSON store."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    seen = {}
    for record in read_all(path):
        url = record.get("url")
        if not url:
            continue
        # The same url can legitimately appear in two files — an archive left over
        # from a previous layout, a month file that was not pruned. Inserting it
        # twice violates the unique constraint and kills the whole run, so dedupe
        # here and keep whichever copy carries a real verdict.
        prior = seen.get(url)
        if prior is not None:
            if prior.importance is None and record.get("importance") is not None:
                prior.importance = record["importance"]
                prior.why = record.get("why") or prior.why
                prior.area = record.get("area") or prior.area
                prior.tags = record.get("tags") or prior.tags
            continue
        row = Article(
            title=record.get("title", ""),
            url=record["url"],
            source=record.get("source", ""),
            published_date=_from_iso(record.get("published_date")),
            summary=record.get("summary", ""),
            relevance_score=record.get("relevance_score", 0.0),
            read_status=record.get("read_status", False),
            tags=record.get("tags", "") or "",
            area=record.get("area") or "other",
            importance=record.get("importance"),
            why=record.get("why") or "",
            first_seen=_from_iso(record.get("first_seen")),
        )
        seen[url] = row
        session.add(row)
    session.commit()
    return session


def dump(session, path=DATA_PATH):
    """Write the session back out as JSON, newest first.

    Sorted output and stable key order keep the daily commit diffs readable.
    """
    articles = []
    for row in session.query(Article).all():
        record = {
            "title": row.title,
            "url": row.url,
            "source": row.source,
            "published_date": _to_iso(row.published_date),
            "summary": row.summary or "",
            "tags": row.tags or "",
            "area": row.area or "other",
        }
        # When we first stored it. "New" must key off this, not published_date: a
        # paper published three days ago and collected today has never been seen.
        if row.first_seen is not None:
            record["first_seen"] = _to_iso(row.first_seen)
        # Absent when only the keyword fallback has seen it, which the page shows
        # as "unrated" rather than inventing a number.
        if row.importance is not None:
            record["importance"] = round(row.importance, 3)
        if row.why:
            record["why"] = row.why
        # The summary is an input to classification, not output, and the page
        # never renders it — it was 55% of the file. Keep it only while a row is
        # still unrated, so reclassify.py has something to judge.
        if row.importance is None and row.summary:
            record["summary"] = row.summary[:600]
        articles.append(record)

    articles.sort(key=lambda a: (a["published_date"] or "", a["url"]), reverse=True)

    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
               - timedelta(days=HOT_DAYS)).isoformat(timespec="seconds")
    hot = [a for a in articles if (a["published_date"] or "") >= cutoff]
    cold = [a for a in articles if (a["published_date"] or "") < cutoff]

    # Carry the outgoing build's stamp forward, so the page can say "arrived in the
    # latest run" without needing per-run bookkeeping anywhere else.
    previous = ""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                previous = json.load(handle).get("generated_at", "")
        except (json.JSONDecodeError, OSError):
            previous = ""

    _write(path, {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_generated_at": previous,
        "hot_days": HOT_DAYS,
        "count": len(hot),
        "total_collected": len(articles),
        "sources": sorted({a["source"] for a in hot}),
        "articles": hot,
    })

    # One file per month, rewritten only when that month's contents change, so
    # the archive is near-static in git.
    months = {}
    for article in cold:
        months.setdefault((article["published_date"] or "")[:7], []).append(article)
    for month, rows in months.items():
        _write_if_changed(os.path.join(ARCHIVE_DIR, f"{month}.json"),
                          {"month": month, "count": len(rows), "articles": rows})

    # Drop month files that no longer hold anything. Without this, rows that move
    # between months leave a stale copy behind and turn up twice on the next read.
    for existing in archive_files():
        month = os.path.basename(existing)[:-len(".json")]
        if month not in months:
            os.remove(existing)

    return len(articles)


def _write(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")


def _write_if_changed(path, payload):
    body = json.dumps(payload, indent=1, ensure_ascii=False) + "\n"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            if handle.read() == body:
                return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return True
