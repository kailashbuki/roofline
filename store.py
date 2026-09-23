"""JSON-backed article store.

data/articles.json is the durable source of truth: diffable in git and served
directly to the static site. SQLite is ephemeral scratch that exists only for
the duration of a collection run, which is what lets the collectors keep using
the SQLAlchemy session interface unchanged.
"""
import json
import os
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Article, Base

DATA_PATH = os.path.join("data", "articles.json")


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


def hydrate(path=DATA_PATH):
    """Build an in-memory SQLite session preloaded from the JSON store."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    for record in read_json(path):
        session.add(Article(
            title=record.get("title", ""),
            url=record["url"],
            source=record.get("source", ""),
            published_date=_from_iso(record.get("published_date")),
            summary=record.get("summary", ""),
            relevance_score=record.get("relevance_score", 0.0),
            read_status=record.get("read_status", False),
            tags=record.get("tags", "") or "",
        ))
    session.commit()
    return session


def dump(session, path=DATA_PATH):
    """Write the session back out as JSON, newest first.

    Sorted output and stable key order keep the daily commit diffs readable.
    """
    articles = []
    for row in session.query(Article).all():
        articles.append({
            "title": row.title,
            "url": row.url,
            "source": row.source,
            "published_date": _to_iso(row.published_date),
            "summary": row.summary or "",
            "relevance_score": round(row.relevance_score or 0.0, 3),
            "tags": row.tags or "",
        })

    articles.sort(key=lambda a: (a["published_date"] or "", a["url"]), reverse=True)

    payload = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "count": len(articles),
        "sources": sorted({a["source"] for a in articles}),
        "articles": articles,
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    return len(articles)
