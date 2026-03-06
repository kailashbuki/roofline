import feedparser
from datetime import datetime
from database import Article

def collect_airealist(session, config):
    """Collect articles from AI Realist (Julien Simon's Substack)"""
    feed_url = 'https://www.airealist.ai/feed'
    count = 0
    
    try:
        feed = feedparser.parse(feed_url)
        
        for entry in feed.entries:
            url = entry.get('link', '')
            
            # Check if already exists
            existing = session.query(Article).filter_by(url=url).first()
            if existing:
                continue
            
            title = entry.get('title', 'No title')
            summary = entry.get('summary', '')
            
            # Parse publication date
            pub_date = datetime.utcnow()
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6])
            
            article = Article(
                title=title[:255],
                url=url,
                source='airealist',
                published_date=pub_date,
                summary=summary[:500] if summary else '',
                relevance_score=1.0,
                tags='ai,llm,inference'
            )
            session.add(article)
            count += 1
        
        session.commit()
        
    except Exception as e:
        print(f"Error collecting AI Realist: {e}")
    
    return count
