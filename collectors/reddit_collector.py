import praw
from datetime import datetime
from database import Article
from relevance_scorer import calculate_relevance, extract_tags

def collect_reddit(session, config):
    reddit_config = config['sources']['reddit']
    if not reddit_config['enabled']:
        return 0
    
    # Note: Requires Reddit API credentials in environment or praw.ini
    try:
        reddit = praw.Reddit(
            client_id='YOUR_CLIENT_ID',
            client_secret='YOUR_CLIENT_SECRET',
            user_agent='inference_dashboard/1.0'
        )
    except:
        print("Reddit API not configured, skipping")
        return 0
    
    count = 0
    keywords = [kw.lower() for kw in reddit_config['keywords']]
    
    for subreddit_name in reddit_config['subreddits']:
        subreddit = reddit.subreddit(subreddit_name)
        
        for submission in subreddit.hot(limit=reddit_config['limit']):
            title = submission.title
            url = submission.url
            
            title_lower = title.lower()
            if not any(kw in title_lower for kw in keywords):
                continue
            
            existing = session.query(Article).filter_by(url=url).first()
            if existing:
                continue
            
            summary = submission.selftext[:500] if submission.selftext else ''
            relevance = calculate_relevance(title, summary, config['relevance'])
            
            if relevance < config['relevance']['min_score']:
                continue
            
            published_date = datetime.fromtimestamp(submission.created_utc)
            
            article = Article(
                title=title,
                url=url,
                source=f'reddit:{subreddit_name}',
                published_date=published_date,
                summary=summary,
                relevance_score=relevance,
                tags=extract_tags(title, summary)
            )
            session.add(article)
            count += 1
    
    session.commit()
    return count
