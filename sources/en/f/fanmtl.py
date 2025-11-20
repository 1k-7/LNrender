# -*- coding: utf-8 -*-
import logging
from typing import Generator
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup, Tag
from lncrawl.models import Chapter
from lncrawl.core.crawler import Crawler

logger = logging.getLogger(__name__)

class FanMTLCrawler(Crawler):
    has_mtl = True
    base_url = "https://www.fanmtl.com/"

    def initialize(self):
        # High concurrency for TOC fetching
        self.init_executor(60) 
        self.cleaner.bad_css.update({'div[align="center"]'})

    def read_novel_info(self):
        logger.debug("Visiting %s", self.novel_url)
        soup = self.get_soup(self.novel_url)

        # 1. Title
        possible_title = soup.select_one(".novel-info h1.novel-title")
        self.novel_title = possible_title.text.strip() if possible_title else "Unknown Novel"

        # 2. Cover
        # Priority: <figure class="cover"> inside header
        img_tag = soup.select_one("figure.cover img")
        if not img_tag:
             # Fallback: Try to find the image inside the fixed-img div
             img_tag = soup.select_one(".fixed-img img")
            
        if img_tag:
            # Get src or data-src (lazy loading)
            url = img_tag.get("src") or img_tag.get("data-src")
            self.novel_cover = self.absolute_url(url)
        
        logger.info("Cover URL found: %s", self.novel_cover)

        # 3. Author
        author_tag = soup.select_one('.novel-info .author span[itemprop="author"]')
        if author_tag:
            text = author_tag.text.strip()
            if "http" not in text and len(text) > 1:
                self.novel_author = text
            else:
                self.novel_author = "Unknown"
        else:
            self.novel_author = "Unknown"

        # 4. Summary
        # Target the specific content div inside the summary section
        summary_div = soup.select_one(".summary .content")
        if summary_div:
            self.novel_synopsis = summary_div.get_text("\n\n").strip()
        else:
            self.novel_synopsis = "Summary not available."

        # 5. Volumes
        self.volumes = [{"id": 1, "title": "Volume 1"}]
        self.chapters = []
        
        # 6. Chapters
        pagination = soup.select('.pagination a[data-ajax-update="#chpagedlist"]')
        
        if not pagination:
            self.parse_chapter_list(soup)
        else:
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
        # FIX: Use extract_contents instead of extract
        return self.cleaner.extract_contents(body)
