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
            
            # Find all article links
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
                
                # Find title - get the longest text in the link
                title = None
                all_text = []
                for elem in link.find_all(['h4', 'h6', 'h2', 'h3', 'span']):
                    text = elem.get_text(strip=True)
                    if text:
                        all_text.append(text)
                
                # Skip category tags and get the longest meaningful text
                skip_words = ['Interpretability', 'Alignment', 'Policy', 'Announcements', 
                             'Societal Impacts', 'Economic Research', 'Product']
                for text in sorted(all_text, key=len, reverse=True):
                    if len(text) > 15 and text not in skip_words:
                        title = text
                        break
                
                if not title:
                    continue
                
                # Find date
                pub_date = datetime.utcnow()
                time_elem = link.find('time')
                if time_elem:
                    date_str = time_elem.get_text(strip=True)
                    try:
                        pub_date = datetime.strptime(date_str, '%b %d, %Y')
                    except:
                        try:
                            pub_date = datetime.strptime(date_str, '%B %d, %Y')
                        except:
                            pass
                
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
