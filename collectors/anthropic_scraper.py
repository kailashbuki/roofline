import requests
from bs4 import BeautifulSoup
from datetime import datetime
from database import Article
from bedrock_classifier import classify_article

def collect_anthropic(session, config):
    # First, get dates from sitemap
    url_dates = {}
    try:
        sitemap_response = requests.get('https://www.anthropic.com/sitemap.xml', timeout=10)
        sitemap_soup = BeautifulSoup(sitemap_response.content, 'html.parser')
        
        for url_elem in sitemap_soup.find_all('url'):
            loc = url_elem.find('loc')
            lastmod = url_elem.find('lastmod')
            if loc and lastmod:
                url_text = loc.get_text(strip=True)
                date_text = lastmod.get_text(strip=True)
                try:
                    # Parse ISO format: 2025-12-14T20:27:33.000Z
                    pub_date = datetime.fromisoformat(date_text.replace('Z', '+00:00'))
                    url_dates[url_text] = pub_date
                except:
                    pass
    except Exception as e:
        print(f"Error fetching sitemap: {e}")
    
    urls = [
        ('https://www.anthropic.com/research', 'anthropic:research'),
        ('https://www.anthropic.com/engineering', 'anthropic:engineering')
    ]
    
    count = 0
    for url, source in urls:
        try:
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            links = soup.find_all('a', href=True)
            
            for link in links:
                href = link.get('href', '')
                
                # Filter by section
                if source == 'anthropic:research':
                    if not ('/research/' in href or '/news/' in href):
                        continue
                elif source == 'anthropic:engineering':
                    if not '/engineering/' in href or href == '/engineering':
                        continue
                
                if not href.startswith('http'):
                    href = f"https://www.anthropic.com{href}"
                
                existing = session.query(Article).filter_by(url=href).first()
                if existing:
                    continue
                
                # Find title
                title = None
                all_text = []
                for elem in link.find_all(['h4', 'h6', 'h2', 'h3', 'span']):
                    text = elem.get_text(strip=True)
                    if text:
                        all_text.append(text)
                
                skip_words = ['Interpretability', 'Alignment', 'Policy', 'Announcements', 
                             'Societal Impacts', 'Economic Research', 'Product']
                for text in sorted(all_text, key=len, reverse=True):
                    if len(text) > 15 and text not in skip_words:
                        title = text
                        break
                
                if not title:
                    continue
                
                # Get date from sitemap
                pub_date = url_dates.get(href, datetime.utcnow())
                
                # Classify with Bedrock
                relevance, tags = classify_article(title, '')
                if relevance < 0.3:  # Lower threshold for Anthropic
                    continue
                
                article = Article(
                    title=title[:255],
                    url=href,
                    source=source,
                    published_date=pub_date,
                    summary='',
                    relevance_score=relevance,
                    tags=tags
                )
                session.add(article)
                count += 1
            
        except Exception as e:
            print(f"Error scraping {url}: {e}")
    
    session.commit()
    return count
