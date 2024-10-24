import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTextEdit, QPushButton, QVBoxLayout, QWidget, QProgressBar,
                             QHBoxLayout, QLineEdit, QFormLayout, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, QObject
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import random
import logging
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

async def fetch_robots_txt(session, base_url):
    robots_url = urljoin(base_url, '/robots.txt')
    try:
        async with session.get(robots_url) as response:
            if response.status == 200:
                return await response.text()
    except Exception as e:
        logging.error(f"Error fetching robots.txt from {base_url}: {str(e)}")
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
                youtube_links = extract_youtube_links(soup)
                return soup, url, title, youtube_links
    except Exception as e:
        logging.error(f"Error fetching {url}: {str(e)}")
    return None

def extract_youtube_links(soup):
    youtube_links = []

    # Hitta iframe-inbäddningar
    iframes = soup.find_all('iframe')
    for iframe in iframes:
        src = iframe.get('src')
        if src and 'youtube.com/embed/' in src:
            youtube_links.append(src)
    
    # Hitta <a>-taggar med klassen "sv-embed"
    a_tags = soup.find_all('a', class_='sv-embed')
    for a_tag in a_tags:
        href = a_tag.get('href')
        if href and 'youtube.com/watch?v=' in href:
            youtube_links.append(href)
            
    return youtube_links

def extract_links(soup, base_url):
    links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        if urlparse(full_url).netloc == urlparse(base_url).netloc:
            links.add(full_url)
    return links

class ScraperSignals(QObject):
    update = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

class ScraperWorker(QThread):
    def __init__(self, config):
        super().__init__()
        self.signals = ScraperSignals()
        self.config = config
        self.is_running = True

    def run(self):
        asyncio.run(self.run_scraper())

    async def run_scraper(self):
        start_url = self.config['start_url']
        max_pages = int(self.config['max_pages'])
        concurrency = int(self.config['concurrency'])
        delay = float(self.config['delay'])

        visited = set()
        to_visit = {start_url}
        youtube_data = []

        try:
            async with aiohttp.ClientSession() as session:
                robots_txt = await fetch_robots_txt(session, start_url)
                robots_parser = RobotFileParser()
                if robots_txt:
                    robots_parser.parse(robots_txt.splitlines())
                else:
                    robots_parser.parse(['User-agent: *', 'Allow: /'])

                while to_visit and len(visited) < max_pages and self.is_running:
                    tasks = []
                    for _ in range(min(concurrency, len(to_visit), max_pages - len(visited))):
                        if not to_visit or not self.is_running:
                            break
                        url = to_visit.pop()
                        if url not in visited:
                            tasks.append(asyncio.create_task(fetch_and_parse(session, url, robots_parser)))

                    for completed_task in asyncio.as_completed(tasks):
                        result = await completed_task
                        if result:
                            soup, url, title, youtube_links = result
                            visited.add(url)
                            message = f"Skrapar: {url}"
                            self.signals.update.emit(message)

                            for link in youtube_links:
                                youtube_data.append((url, title, link))
                                self.signals.update.emit(f"<b>Hittade YouTube-länk på {url}: {link}</b>")

                            new_links = extract_links(soup, start_url)
                            to_visit.update(new_links - visited)

                        progress = int((len(visited) / max_pages) * 100)
                        self.signals.progress.emit(progress)

                        await asyncio.sleep(delay)

        except Exception as e:
            self.signals.error.emit(f"Ett fel uppstod: {str(e)}")
        finally:
            self.signals.finished.emit(youtube_data)

    def stop(self):
        self.is_running = False

class ScraperGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube-Skrapare")
        self.setGeometry(100, 100, 500, 500)

        main_layout = QVBoxLayout()

        # Configuration form
        form_layout = QFormLayout()
        self.start_url_input = QLineEdit()
        self.max_pages_input = QLineEdit()
        self.concurrency_input = QLineEdit()
        self.delay_input = QLineEdit()

        form_layout.addRow("<b>Domän att skrapa:</b>", self.start_url_input)
        form_layout.addRow("<b>Max antal sidor:</b>", self.max_pages_input)
        form_layout.addRow("<b>Samtidiga skrapningar:</b>", self.concurrency_input)
        form_layout.addRow("<b>Fördröjning i sekunder:</b>", self.delay_input)

        main_layout.addLayout(form_layout)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        main_layout.addWidget(self.text_area)

        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Starta skrapning")
        self.start_button.clicked.connect(self.start_scraping)
        button_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stoppa skrapning")
        self.stop_button.clicked.connect(self.stop_scraping)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        main_layout.addLayout(button_layout)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.worker = None

    def start_scraping(self):
        config = self.get_config()
        if not config:
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.text_area.clear()
        self.progress_bar.setValue(0)

        self.worker = ScraperWorker(config)
        self.worker.signals.update.connect(self.update_text)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.finished.connect(self.scraping_finished)
        self.worker.signals.error.connect(self.handle_error)
        self.worker.start()

    def get_config(self):
        start_url = self.start_url_input.text()
        max_pages = self.max_pages_input.text()
        concurrency = self.concurrency_input.text()
        delay = self.delay_input.text()

        if not all([start_url, max_pages, concurrency, delay]):
            QMessageBox.warning(self, "Ogiltig inmatning", "Alla fält måste fyllas i.")
            return None

        try:
            max_pages = int(max_pages)
            concurrency = int(concurrency)
            delay = float(delay)
        except ValueError:
            QMessageBox.warning(self, "Ogiltiga värden", "Max antal sidor och Antal samtidiga sidor måste vara heltal, Fördröjning måste vara ett numeriskt värde.")
            return None

        return {
            "start_url": start_url,
            "max_pages": max_pages,
            "concurrency": concurrency,
            "delay": delay
        }

    def stop_scraping(self):
        if self.worker:
            self.worker.stop()
            self.text_area.append("<b>Stoppar skrapningen...</b>")

    def update_text(self, message):
        self.text_area.append(message)
        self.text_area.ensureCursorVisible()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def scraping_finished(self, youtube_data):
        self.text_area.append("")
        self.text_area.append("\n<b>Skrapning klar!</b>")
        self.text_area.append("")
        self.text_area.append("------------------------")
        if youtube_data:
            self.text_area.append("")
            self.text_area.append(f"<b>Totalt antal hittade YouTube-inbäddningar:</b> {len(youtube_data)}\n")
            self.text_area.append("")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(100)

        # Lägg till hittade YouTube-länkar
        if youtube_data:
            for url, title, youtube_link in youtube_data:
                self.text_area.append(f"<b>{title}</b>")
                self.text_area.append(f"{url}")
                self.text_area.append(f"{youtube_link}\n")

        # Skriv resultaten till en fil
        with open('resultat.txt', 'w', encoding='utf-8') as f:
            for url, title, youtube_link in youtube_data:
                f.write(f"URL: {url}\n")
                f.write(f"Sida: {title}\n")
                f.write(f"YouTube-video: {youtube_link}\n\n")

        if youtube_data:
            self.text_area.append("---------------------------------------")
            self.text_area.append("")
            self.text_area.append("Resultaten har sparats i 'resultat.txt'")
        else:
            self.text_area.append("")
            self.text_area.append("Inga YouTube-länkar hittades.")

    def handle_error(self, error_message):
        self.text_area.append(f"ERROR: {error_message}")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = ScraperGUI()
    gui.show()
    sys.exit(app.exec_())