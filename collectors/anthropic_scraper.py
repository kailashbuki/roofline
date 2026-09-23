from datetime import datetime

import requests
from bs4 import BeautifulSoup

from collectors import pipeline

SITEMAP = 'https://www.anthropic.com/sitemap.xml'
SECTIONS = [
    ('https://www.anthropic.com/research', 'anthropic:research'),
    ('https://www.anthropic.com/engineering', 'anthropic:engineering'),
]
SKIP_WORDS = {
    'Interpretability', 'Alignment', 'Policy', 'Announcements',
    'Societal Impacts', 'Economic Research', 'Product',
}


def _sitemap_dates():
    """The listing pages are JS-rendered, so dates come from the sitemap."""
    dates = {}
    try:
        response = requests.get(SITEMAP, timeout=10)
        soup = BeautifulSoup(response.content, 'xml')
    except Exception as exc:
        print(f"    Error fetching sitemap: {exc}")
        return dates

    for url_elem in soup.find_all('url'):
        loc = url_elem.find('loc')
        lastmod = url_elem.find('lastmod')
        if not (loc and lastmod):
            continue
        try:
            parsed = datetime.fromisoformat(
                lastmod.get_text(strip=True).replace('Z', '+00:00')
            )
            dates[loc.get_text(strip=True)] = parsed.replace(tzinfo=None)
        except ValueError:
            pass
    return dates


def _title_from(link):
    texts = [
        elem.get_text(strip=True)
        for elem in link.find_all(['h4', 'h6', 'h2', 'h3', 'span'])
        if elem.get_text(strip=True)
    ]
    for text in sorted(texts, key=len, reverse=True):
        if len(text) > 15 and text not in SKIP_WORDS:
            return text
    return None


def collect_anthropic(session, config):
    url_dates = _sitemap_dates()

    rows = []
    for page_url, source in SECTIONS:
        try:
            response = requests.get(page_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
        except Exception as exc:
            print(f"    Error scraping {page_url}: {exc}")
            continue

        for link in soup.find_all('a', href=True):
            href = link.get('href', '')

            if source == 'anthropic:research':
                if not ('/research/' in href or '/news/' in href):
                    continue
            elif '/engineering/' not in href or href == '/engineering':
                continue

            if not href.startswith('http'):
                href = f"https://www.anthropic.com{href}"

            title = _title_from(link)
            if not title:
                continue

            rows.append({
                "title": title,
                "url": href,
                "source": source,
                "published_date": url_dates.get(href, datetime.utcnow()),
                "summary": "",
            })

    return pipeline.commit(session, config, rows)
