# -*- coding: utf-8 -*-
import logging
from typing import Generator
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup, Tag

from lncrawl.models import Chapter
from lncrawl.templates.browser.chapter_only import ChapterOnlyBrowserTemplate

logger = logging.getLogger(__name__)


class FanMTLCrawler(ChapterOnlyBrowserTemplate):
    has_mtl = True
    base_url = "https://www.fanmtl.com/"

    def initialize(self):
        # Force high concurrency here as well for safety, 
        # though bot.py overrides it usually.
        self.init_executor(10) 
        self.cleaner.bad_css.update(
            {
                'div[align="center"]',
            }
        )

    def parse_title(self, soup: BeautifulSoup) -> str:
        possible_title = soup.select_one(".novel-info .novel-title")
        assert possible_title, "No novel title"
        return possible_title.text.strip()

    def parse_cover(self, soup: BeautifulSoup) -> str:
        possible_image = soup.select_one(".novel-header figure.cover img")
        if possible_image:
            return self.absolute_url(possible_image["src"])

    def parse_authors(self, soup: BeautifulSoup) -> Generator[str, None, None]:
        possible_author = soup.select_one('.novel-info .author span[itemprop="author"]')
        if possible_author:
            yield possible_author.text.strip()

    def select_chapter_tags(self, soup: BeautifulSoup) -> Generator[Tag, None, None]:
        # FIX: Check if pagination exists
        pagination = soup.select('.pagination a[data-ajax-update="#chpagedlist"]')
        
        if not pagination:
            # Case 1: No pagination (Single page novel)
            yield from soup.select("ul.chapter-list li a")
            return

        # Case 2: Pagination exists (Multi-page novel)
        last_page = pagination[-1]
        last_page_url = self.absolute_url(last_page["href"])
        
        # Extract base URL and params
        common_page_url = last_page_url.split("?")[0]
        params = parse_qs(urlparse(last_page_url).query)
        
        # Calculate total pages safely
        try:
            page_count = int(params.get("page", [0])[0]) + 1
            wjm_param = params.get("wjm", [""])[0]
        except (IndexError, ValueError):
             # Fallback if URL parsing fails
            yield from soup.select("ul.chapter-list li a")
            return

        # Queue up all pages
        futures = []
        for page in range(page_count):
            page_url = f"{common_page_url}?page={page}&wjm={wjm_param}"
            futures.append(self.executor.submit(self.get_soup, page_url))
            
        # Resolve and yield
        for soup in self.resolve_futures(futures, desc="TOC", unit="page"):
            yield from soup.select("ul.chapter-list li a")

    def parse_chapter_item(self, tag: Tag, id: int) -> Chapter:
        return Chapter(
            id=id,
            url=self.absolute_url(tag["href"]),
            title=tag.select_one(".chapter-title").text.strip(),
        )

    def select_chapter_body(self, soup: BeautifulSoup) -> Tag:
        return soup.select_one("#chapter-article .chapter-content")
