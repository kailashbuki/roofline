import arxiv
from datetime import datetime, timedelta
from database import Article
from classifier import classify_article

def collect_arxiv(session, config):
    arxiv_config = config['sources']['arxiv']
    if not arxiv_config['enabled']:
        return 0
    
    keywords = ' OR '.join(arxiv_config['keywords'])
    search = arxiv.Search(
        query=keywords,
        max_results=arxiv_config['max_results'],
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    
    # Must have at least one of these
    performance_keywords = ['latency', 'throughput', 'gpu', 'tpu', 'accelerator', 
                           'serving', 'quantization', 'cuda', 'tensor core', 'optimization']
    
    # Must have at least one of these
    model_keywords = ['llm', 'language model', 'transformer', 'neural network', 'deep learning']
    
    count = 0
    for result in search.results():
        existing = session.query(Article).filter_by(url=result.entry_id).first()
        if existing:
            continue
        
        summary = result.summary[:1000]
        
        # Score and tag via Gemini (keyword fallback if unavailable)
        relevance, tags = classify_article(result.title, summary)
        
        if relevance < config['relevance']['min_score']:
            continue
        
        article = Article(
            title=result.title,
            url=result.entry_id,
            source='arxiv',
            published_date=result.published,
            summary=summary,
            relevance_score=relevance,
            tags=tags
        )
        session.add(article)
        count += 1
    
    session.commit()
    return count
