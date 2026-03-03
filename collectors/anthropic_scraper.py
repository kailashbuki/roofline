import requests
from bs4 import BeautifulSoup
from datetime import datetime
from database import Article
import re

def collect_anthropic(session, config):
    urls = [
        ('https://www.anthropic.com/research', 'anthropic:research'),
        ('https://www.anthropic.com/engineering', 'anthropic:engineering')
    ]
    
    count = 0
    for url, source in urls:
        try:
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Build a map of URLs to dates by finding all time elements
            url_dates = {}
            for time_elem in soup.find_all('time'):
                date_str = time_elem.get_text(strip=True)
                # Find the nearest link
                parent = time_elem.parent
                for _ in range(5):  # Search up to 5 levels up
                    if not parent:
                        break
                    link = parent.find('a', href=True)
                    if link:
                        href = link.get('href', '')
                        if href and (source == 'anthropic:research' and ('/research/' in href or '/news/' in href) or
                                    source == 'anthropic:engineering' and '/engineering/' in href):
                            try:
                                pub_date = datetime.strptime(date_str, '%b %d, %Y')
                                url_dates[href] = pub_date
                            except:
                                try:
                                    pub_date = datetime.strptime(date_str, '%B %d, %Y')
                                    url_dates[href] = pub_date
                                except:
                                    pass
                            break
                    parent = parent.parent
            
            # Now collect articles
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
                
                # Get date from our map
                pub_date = url_dates.get(link.get('href', ''), datetime.utcnow())
                
                article = Article(
                    title=title[:255],
                    url=href,
                    source=source,
                    published_date=pub_date,
                    summary='',
                    relevance_score=1.0,
                    tags='anthropic'
                )
                session.add(article)
                count += 1
            
        except Exception as e:
            print(f"Error scraping {url}: {e}")
    
    session.commit()
    return count
