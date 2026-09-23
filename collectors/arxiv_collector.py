import arxiv

from collectors import pipeline


def collect_arxiv(session, config):
    arxiv_config = config['sources']['arxiv']
    if not arxiv_config['enabled']:
        return 0

    # The arXiv query is retrieval, not relevance: cast a wide net over the
    # relevant categories and let the classifier judge. Keeping it broad is why
    # architecture and training papers show up at all.
    categories = " OR ".join(f"cat:{c}" for c in arxiv_config['categories'])
    terms = " OR ".join(f'abs:"{k}"' for k in arxiv_config['query_terms'])
    search = arxiv.Search(
        query=f"({categories}) AND ({terms})",
        max_results=arxiv_config['max_results'],
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )

    rows = []
    for result in search.results():
        rows.append({
            "title": result.title,
            "url": result.entry_id,
            "source": "arxiv",
            "published_date": result.published,
            "summary": result.summary[:1000],
        })

    return pipeline.commit(session, config, rows)
