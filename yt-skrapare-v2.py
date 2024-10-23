import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QPushButton, QVBoxLayout, QWidget, QProgressBar, QStyleFactory
from PyQt5.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt5 import QtWidgets, QtGui
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import random
import logging
import json
from urllib.robotparser import RobotFileParser

# Konfigurera loggning
logging.basicConfig(filename='scraper.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Lista med user agents för rotation
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.77 Safari/537.36'
]

def read_config():
    with open('config.json', 'r') as f:
        return json.load(f)

async def fetch_robots_txt(session, base_url):
    robots_url = urljoin(base_url, '/robots.txt')
    async with session.get(robots_url) as response:
        if response.status == 200:
            return await response.text()
    return None

async def fetch_and_parse(session, url, robots_parser):
    if not robots_parser.can_fetch("*", url):
        logging.info(f"Skipping {url} as per robots.txt")
        return None

    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
                title = soup.title.string if soup.title else "Ingen titel"
                return soup, url, title
    except Exception as e:
        logging.error(f"Error fetching {url}: {str(e)}")
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

async def crawl_website(start_url, max_pages, concurrency, queue):
    visited = set()
    to_visit = {start_url}
    youtube_data = []

    async with aiohttp.ClientSession() as session:
        robots_txt = await fetch_robots_txt(session, start_url)
        robots_parser = RobotFileParser()
        if robots_txt:
            robots_parser.parse(robots_txt.splitlines())
        else:
            robots_parser.parse(['User-agent: *', 'Allow: /'])

        while to_visit and len(visited) < max_pages:
            tasks = []
            for _ in range(min(concurrency, len(to_visit))):
                if not to_visit:
                    break
                url = to_visit.pop()
                if url not in visited:
                    tasks.append(asyncio.create_task(fetch_and_parse(session, url, robots_parser)))

            for completed_task in asyncio.as_completed(tasks):
                result = await completed_task
                if result:
                    soup, url, title = result
                    visited.add(url)
                    message = f"Skrapar: {url}"
                    logging.info(message)
                    await queue.put(message)

                    youtube_links = extract_youtube_links(soup)
                    for link in youtube_links:
                        youtube_data.append((url, title, link))
                        await queue.put(f"Hittade YouTube-länk på {url}: {link}")

                    new_links = extract_links(soup, start_url)
                    to_visit.update(new_links - visited)

                await asyncio.sleep(0.5)  # Lägg till en halv sekunds fördröjning

    await queue.put("DONE")  # Signal för att skrapningen är klar
    return youtube_data

class ScraperSignals(QObject):
    update = pyqtSignal(str)
    finished = pyqtSignal(list)

class ScraperWorker(QThread):
    def __init__(self):
        super().__init__()
        self.signals = ScraperSignals()

    def run(self):
        asyncio.run(self.run_scraper())

    async def run_scraper(self):
        config = read_config()
        start_url = config['start_url']
        max_pages = config.get('max_pages', 5000)
        concurrency = config.get('concurrency', 5)

        queue = asyncio.Queue()
        youtube_data = await crawl_website(start_url, max_pages, concurrency, queue)

        while True:
            try:
                message = queue.get_nowait()
                if message == "DONE":
                    break
                self.signals.update.emit(message)
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)

        self.signals.finished.emit(youtube_data)

class ScraperGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube-Skrapare")
        self.setGeometry(100, 100, 800, 600)

        layout = QVBoxLayout()

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        layout.addWidget(self.text_area)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.start_button = QPushButton("Starta Skrapning")
        self.start_button.clicked.connect(self.start_scraping)
        layout.addWidget(self.start_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.worker = None

    def start_scraping(self):
        self.start_button.setEnabled(False)
        self.text_area.clear()
        self.progress_bar.setValue(0)

        self.worker = ScraperWorker()
        self.worker.signals.update.connect(self.update_text)
        self.worker.signals.finished.connect(self.scraping_finished)
        self.worker.start()

    def update_text(self, message):
        self.text_area.append(message)
        self.text_area.ensureCursorVisible()

    def scraping_finished(self, youtube_data):
        self.text_area.append("\nSkrapning klar. Sammanfattning av resultat:\n")
        self.text_area.append(f"Totalt antal hittade YouTube-länkar: {len(youtube_data)}\n")
        self.start_button.setEnabled(True)
        self.progress_bar.setValue(100)

        # Skriv resultaten till en fil
        with open('resultat.txt', 'w', encoding='utf-8') as f:
            for url, title, youtube_link in youtube_data:
                f.write(f"URL: {url}\n")
                f.write(f"Sida: {title}\n")
                f.write(f"YouTube-video: {youtube_link}\n\n")

        self.text_area.append("Resultaten har sparats i 'resultat.txt'")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = ScraperGUI()
    gui.show()
    sys.exit(app.exec_())
