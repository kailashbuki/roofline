# Inference Optimization Dashboard

Daily aggregation of inference optimization research and content from multiple sources.

## Quick Start

1. Install dependencies:
```bash
cd ~/Workplace/daily_news
pip install -r requirements.txt
```

2. Run initial collection:
```bash
python collect_all.py
```

3. Start dashboard:
```bash
python dashboard_server.py
```

Visit: http://localhost:8001

## Components

- `database.py` - SQLite database models
- `relevance_scorer.py` - Content relevance scoring
- `collectors/` - Data collection modules
  - `arxiv_collector.py` - arXiv papers
  - `hackernews_collector.py` - HackerNews stories
  - `rss_collector.py` - RSS feeds (HuggingFace, PyTorch, etc.)
  - `reddit_collector.py` - Reddit posts
- `collect_all.py` - Run all collectors
- `dashboard_server.py` - FastAPI backend
- `static/index.html` - Frontend UI
- `scheduler.py` - Automated collection scheduler
- `config.yaml` - Configuration

## Usage

### Manual Collection
```bash
python collect_all.py
```

### Start Dashboard
```bash
python dashboard_server.py
```

### Run Scheduler (Background)
```bash
python scheduler.py
```

Or use nohup:
```bash
nohup python scheduler.py > scheduler.log 2>&1 &
```

## Configuration

Edit `config.yaml` to:
- Enable/disable sources
- Adjust keywords and filters
- Change collection times
- Modify relevance scoring

## Reddit Setup (Optional)

1. Create Reddit app at https://www.reddit.com/prefs/apps
2. Update `collectors/reddit_collector.py` with credentials
3. Or create `praw.ini` file

## Features

- Multi-source aggregation (arXiv, HackerNews, RSS, Reddit)
- Relevance scoring and filtering
- Tag-based categorization
- Read/unread tracking
- Time-based filtering
- Source filtering
- Responsive web UI
