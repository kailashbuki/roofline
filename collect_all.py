from database import init_db, load_config
from collectors.arxiv_collector import collect_arxiv
from collectors.hackernews_collector import collect_hackernews
from collectors.rss_collector import collect_rss
from collectors.reddit_collector import collect_reddit
from collectors.twitter_collector import collect_twitter
from collectors.anthropic_scraper import collect_anthropic
from collectors.airealist_collector import collect_airealist
from datetime import datetime

def run_collection():
    config = load_config()
    session = init_db(config['database']['path'])
    
    print(f"[{datetime.now()}] Starting collection...")
    
    arxiv_count = collect_arxiv(session, config)
    print(f"  arXiv: {arxiv_count} new articles")
    
    hn_count = collect_hackernews(session, config)
    print(f"  HackerNews: {hn_count} new articles")
    
    rss_count = collect_rss(session, config)
    print(f"  RSS Feeds: {rss_count} new articles")
    
    twitter_count = collect_twitter(session, config)
    print(f"  Twitter: {twitter_count} new articles")
    
    reddit_count = collect_reddit(session, config)
    print(f"  Reddit: {reddit_count} new articles")
    
    anthropic_count = collect_anthropic(session, config)
    print(f"  Anthropic: {anthropic_count} new articles")
    
    airealist_count = collect_airealist(session, config)
    print(f"  AI Realist: {airealist_count} new articles")
    
    total = arxiv_count + hn_count + rss_count + twitter_count + reddit_count + anthropic_count + airealist_count
    print(f"Total: {total} new articles collected\n")
    
    return total

if __name__ == "__main__":
    run_collection()
