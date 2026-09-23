import requests
from datetime import datetime, timedelta
from database import Article
from classifier import classify_article

def collect_hackernews(session, config):
    hn_config = config['sources']['hackernews']
    if not hn_config['enabled']:
        return 0
    
    # Get top stories
    top_stories_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    response = requests.get(top_stories_url)
    story_ids = response.json()[:hn_config['max_items']]
    
    count = 0
    keywords = [kw.lower() for kw in hn_config['keywords']]
    
    for story_id in story_ids:
        story_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        story_response = requests.get(story_url)
        story = story_response.json()
        
        if not story or story.get('type') != 'story':
            continue
        
        title = story.get('title', '')
        url = story.get('url', f"https://news.ycombinator.com/item?id={story_id}")
        
        # Check if relevant
        title_lower = title.lower()
        if not any(kw in title_lower for kw in keywords):
            continue
        
        existing = session.query(Article).filter_by(url=url).first()
        if existing:
            continue
        
        summary = story.get('text', '')[:500] if story.get('text') else ''
        relevance, tags = classify_article(title, summary)
        
        if relevance < config['relevance']['min_score']:
            continue
        
        published_date = datetime.fromtimestamp(story.get('time', 0))
        
        article = Article(
            title=title,
            url=url,
            source='hackernews',
            published_date=published_date,
            summary=summary,
            relevance_score=relevance,
            tags=tags
        )
        session.add(article)
        count += 1
    
    session.commit()
    return count
