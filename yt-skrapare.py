import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time

def read_config():
    with open('config.txt', 'r') as f:
        return f.read().strip()

start_url = read_config()

def fetch_and_parse(url):
    response = requests.get(url)
    if response.status_code == 200:
        return BeautifulSoup(response.text, 'html.parser')
    return None

def extract_youtube_links(soup):
    youtube_links = []
    iframes = soup.find_all('iframe')
    for iframe in iframes:
        src = iframe.get('src')
        if src and 'youtube.com/embed/' in src:
            youtube_links.append(src)
    return youtube_links

def extract_links(soup, base_url):
    links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        if urlparse(full_url).netloc == urlparse(base_url).netloc:
            links.add(full_url)
    return links

def crawl_website(start_url, max_pages=5000):
    visited = set()
    to_visit = {start_url}
    youtube_data = []

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop()
        if url in visited:
            continue

        print(f"Skrapar: {url}")
        soup = fetch_and_parse(url)
        if soup:
            visited.add(url)
            youtube_links = extract_youtube_links(soup)
            for link in youtube_links:
                youtube_data.append((url, link))
            new_links = extract_links(soup, start_url)
            to_visit.update(new_links - visited)

        time.sleep(1)

    return youtube_data

youtube_data = crawl_website(start_url)

print("Hittade YouTube-klipp:")
for page, link in youtube_data:
    print(f"Sida: {page} \nYouTube-video: {link}\n")
