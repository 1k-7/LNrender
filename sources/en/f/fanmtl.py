# -*- coding: utf-8 -*-
import logging
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from lncrawl.models import Chapter
from lncrawl.core.crawler import Crawler

logger = logging.getLogger(__name__)

class FanMTLCrawler(Crawler):
    has_mtl = True
    base_url = "https://www.fanmtl.com/"

    def initialize(self):
        # 1. HIGH SPEED: 60 Threads
        self.init_executor(60)
        
        # 2. CONNECTION POOLING: Allow 60 simultaneous connections
        # Without this, Python limits you to 10, making extra threads useless.
        adapter = HTTPAdapter(
            pool_connections=60, 
            pool_maxsize=60,
            max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        )
        self.scraper.mount("https://", adapter)
        self.scraper.mount("http://", adapter)

    def read_novel_info(self):
        logger.debug("Visiting %s", self.novel_url)
        soup = self.get_soup(self.novel_url)

        # --- TITLE ---
        possible_title = soup.select_one("h1.novel-title")
        self.novel_title = possible_title.text.strip() if possible_title else "Unknown Novel"

        # --- COVER ---
        # Matches <figure class="cover"><img src="...">
        img_tag = soup.select_one("figure.cover img")
        if not img_tag:
            img_tag = soup.select_one(".fixed-img img")
        
        if img_tag:
            url = img_tag.get("src")
            # FanMTL sometimes puts the real image in data-src
            if "placeholder" in str(url) and img_tag.get("data-src"):
                url = img_tag.get("data-src")
            self.novel_cover = self.absolute_url(url)

        # --- AUTHOR ---
        # Matches <div class="author">...<span itemprop="author">
        author_tag = soup.select_one('.novel-info .author span[itemprop="author"]')
        if author_tag:
            text = author_tag.text.strip()
            self.novel_author = text if "http" not in text else "Unknown"
        else:
            self.novel_author = "Unknown"

        # --- SUMMARY ---
        # Matches <div class="summary">...<div class="content">
        summary_div = soup.select_one(".summary .content")
        if summary_div:
            self.novel_synopsis = summary_div.get_text("\n\n").strip()
        else:
            self.novel_synopsis = "Summary not available."

        # --- VOLUMES & CHAPTERS ---
        self.volumes = [{"id": 1, "title": "Volume 1"}]
        self.chapters = []
        
        pagination = soup.select('.pagination a[data-ajax-update="#chpagedlist"]')
        
        if not pagination:
            self.parse_chapter_list(soup)
        else:
            # Get last page number
            last_page = pagination[-1]
            last_page_url = self.absolute_url(last_page["href"])
            common_page_url = last_page_url.split("?")[0]
            params = parse_qs(urlparse(last_page_url).query)
            
            try:
                page_count = int(params.get("page", [0])[0]) + 1
                wjm_param = params.get("wjm", [""])[0]
                
                futures = []
                for page in range(page_count):
                    page_url = f"{common_page_url}?page={page}&wjm={wjm_param}"
                    futures.append(self.executor.submit(self.get_soup, page_url))
                
                for page_soup in self.resolve_futures(futures, desc="TOC", unit="page"):
                    self.parse_chapter_list(page_soup)
            except Exception as e:
                logger.error("Pagination error: %s", e)
                self.parse_chapter_list(soup)

        self.chapters.sort(key=lambda x: x["id"])

    def parse_chapter_list(self, soup):
        for a in soup.select("ul.chapter-list li a"):
            try:
                chap_id = len(self.chapters) + 1
                self.chapters.append(Chapter(
                    id=chap_id,
                    volume=1,
                    url=self.absolute_url(a["href"]),
                    title=a.select_one(".chapter-title").text.strip(),
                ))
            except Exception:
                pass

    def download_chapter_body(self, chapter):
        soup = self.get_soup(chapter["url"])
        body = soup.select_one("#chapter-article .chapter-content")
        
        if not body:
            return "<p>Content not found on source site.</p>"

        # --- CRITICAL FIX ---
        # The method is 'extract_contents', NOT 'extract'.
        # This was causing the crash and empty files.
        content = self.cleaner.extract_contents(body)
        
        if not content:
            return "<p>Empty content.</p>"
            
        return content
