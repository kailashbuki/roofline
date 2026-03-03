import tweepy
from datetime import datetime, timedelta
from database import Article
from relevance_scorer import calculate_relevance, extract_tags

def collect_twitter(session, config):
    twitter_config = config['sources']['twitter']
    if not twitter_config['enabled']:
        return 0
    
    # Check if credentials are set
    if twitter_config['api_key'] == "YOUR_API_KEY":
        print("Twitter API credentials not configured, skipping")
        return 0
    
    try:
        # OAuth 1.0a authentication
        auth = tweepy.OAuthHandler(
            twitter_config['api_key'],
            twitter_config['api_secret']
        )
        auth.set_access_token(
            twitter_config['access_token'],
            twitter_config['access_token_secret']
        )
        api = tweepy.API(auth)
        
        # Get your own tweets and likes (free tier allows this)
        me = api.verify_credentials()
        
        # Get your recent tweets
        my_tweets = api.user_timeline(
            screen_name=me.screen_name,
            count=50,
            tweet_mode='extended'
        )
        
        # Get your liked tweets
        liked_tweets = api.get_favorites(
            screen_name=me.screen_name,
            count=50,
            tweet_mode='extended'
        )
        
        all_tweets = my_tweets + liked_tweets
        
        if not all_tweets:
            print("No tweets found")
            return 0
        
        count = 0
        keywords = [kw.lower() for kw in twitter_config['keywords']]
        
        for tweet in all_tweets:
            text = tweet.full_text if hasattr(tweet, 'full_text') else tweet.text
            
            # Check if relevant
            text_lower = text.lower()
            if not any(kw in text_lower for kw in keywords):
                continue
            
            # Get tweet URL
            url = f"https://twitter.com/{tweet.user.screen_name}/status/{tweet.id}"
            
            existing = session.query(Article).filter_by(url=url).first()
            if existing:
                continue
            
            title = f"@{tweet.user.screen_name}: {text[:100]}..."
            summary = text[:500]
            
            relevance = calculate_relevance(title, summary, config['relevance'])
            if relevance < config['relevance']['min_score']:
                continue
            
            article = Article(
                title=title,
                url=url,
                source='twitter',
                published_date=tweet.created_at,
                summary=summary,
                relevance_score=relevance,
                tags=extract_tags(title, summary)
            )
            session.add(article)
            count += 1
        
        session.commit()
        return count
        
    except Exception as e:
        print(f"Error fetching Twitter feed: {e}")
        return 0
