from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import desc
from database import init_db, load_config, Article
from datetime import datetime, timedelta
import os
import asyncio
from typing import Dict

app = FastAPI(title="Inference Optimization Dashboard")

config = load_config()
session = init_db(config['database']['path'])

# Global state for collection progress
collection_state: Dict = {
    "running": False,
    "progress": [],
    "total": 0,
    "completed": 0
}

@app.get("/")
async def root():
    return HTMLResponse(open('static/index.html').read())

@app.get("/api/articles")
async def get_articles(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    source: str = None,
    tag: str = None,
    unread_only: bool = False,
    days: int = Query(7, ge=1)
):
    query = session.query(Article)
    
    # Filter by date
    since = datetime.utcnow() - timedelta(days=days)
    query = query.filter(Article.published_date >= since)
    
    # Filter by source
    if source:
        query = query.filter(Article.source.like(f"%{source}%"))
    
    # Filter by tag
    if tag:
        query = query.filter(Article.tags.like(f"%{tag}%"))
    
    # Filter by read status
    if unread_only:
        query = query.filter(Article.read_status == False)
    
    # Order by relevance and date
    query = query.order_by(desc(Article.relevance_score), desc(Article.published_date))
    
    # Pagination
    total = query.count()
    articles = query.offset((page - 1) * per_page).limit(per_page).all()
    
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "articles": [{
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_date": a.published_date.isoformat() if a.published_date else None,
            "summary": a.summary,
            "relevance_score": a.relevance_score,
            "read_status": a.read_status,
            "tags": a.tags.split(',') if a.tags else []
        } for a in articles]
    }

@app.post("/api/articles/{article_id}/mark_read")
async def mark_read(article_id: int):
    article = session.query(Article).filter_by(id=article_id).first()
    if article:
        article.read_status = True
        session.commit()
        return {"success": True}
    return {"success": False}

@app.get("/api/stats")
async def get_stats():
    total = session.query(Article).count()
    unread = session.query(Article).filter_by(read_status=False).count()
    today = datetime.utcnow().date()
    today_count = session.query(Article).filter(
        Article.published_date >= datetime.combine(today, datetime.min.time())
    ).count()
    
    sources = session.query(Article.source).distinct().all()
    
    return {
        "total_articles": total,
        "unread_articles": unread,
        "today_articles": today_count,
        "sources": [s[0] for s in sources]
    }

@app.post("/api/collect")
async def start_collection():
    if collection_state["running"]:
        return {"status": "already_running"}
    
    asyncio.create_task(run_collection_async())
    return {"status": "started"}

@app.get("/api/collect/progress")
async def get_collection_progress():
    return collection_state

async def run_collection_async():
    from collectors.arxiv_collector import collect_arxiv
    from collectors.hackernews_collector import collect_hackernews
    from collectors.rss_collector import collect_rss
    from collectors.reddit_collector import collect_reddit
    from collectors.twitter_collector import collect_twitter
    from collectors.anthropic_scraper import collect_anthropic
    
    collection_state["running"] = True
    collection_state["progress"] = []
    collection_state["total"] = 0
    collection_state["completed"] = 0
    
    collectors = [
        ("arXiv", collect_arxiv),
        ("HackerNews", collect_hackernews),
        ("RSS Feeds", collect_rss),
        ("Twitter", collect_twitter),
        ("Reddit", collect_reddit),
        ("Anthropic", collect_anthropic)
    ]
    
    for name, collector in collectors:
        try:
            count = await asyncio.to_thread(collector, session, config)
            collection_state["progress"].append({"source": name, "count": count, "status": "done"})
            collection_state["total"] += count
            collection_state["completed"] += 1
        except Exception as e:
            collection_state["progress"].append({"source": name, "count": 0, "status": f"error: {str(e)}"})
            collection_state["completed"] += 1
    
    collection_state["running"] = False

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config['dashboard']['host'], port=config['dashboard']['port'])
