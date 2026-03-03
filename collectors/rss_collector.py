import feedparser
from datetime import datetime
from database import Article
from bedrock_classifier import classify_article
import time

def collect_rss(session, config):
    rss_config = config['sources']['rss_feeds']
    if not rss_config['enabled']:
        return 0
    
    count = 0
    for feed_info in rss_config['feeds']:
        try:
            feed = feedparser.parse(feed_info['url'])
            
            for entry in feed.entries[:20]:
                url = entry.get('link', '')
                if not url:
                    continue
                
                existing = session.query(Article).filter_by(url=url).first()
                if existing:
                    continue
                
                title = entry.get('title', '')
                summary = entry.get('summary', entry.get('description', ''))[:1000]
                
                # Skip filtering for these sources - everything is relevant
                if any(name in feed_info['name'] for name in ['SemiAnalysis', 'Microsoft AI', 'vLLM', 'Together.ai', 'NVIDIA Developer']):
                    relevance = 1.0
                    tags = ""
                else:
                    relevance, tags = classify_article(title, summary)
                    if relevance < config['relevance']['min_score']:
                        continue
                
                published = entry.get('published_parsed') or entry.get('updated_parsed')
                published_date = datetime(*published[:6]) if published else datetime.utcnow()
                
                article = Article(
                    title=title,
                    url=url,
                    source=f"rss:{feed_info['name']}",
                    published_date=published_date,
                    summary=summary,
                    relevance_score=relevance,
                    tags=tags
                )
                session.add(article)
                count += 1
            
            time.sleep(1)  # Rate limiting
        except Exception as e:
            print(f"Error fetching {feed_info['name']}: {e}")
    
    session.commit()
    return count
