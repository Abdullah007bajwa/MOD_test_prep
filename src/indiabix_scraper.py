"""
Extract IndiaBix logical-reasoning MCQs via live HTTP requests.
Maps questions to gat category with sub_category from URL slug.
"""
import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict
from uuid import uuid5, NAMESPACE_DNS

import requests
from bs4 import BeautifulSoup

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.indiabix.com/logical-reasoning/{topic}/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_DELAY = 1
MAX_RETRIES = 3

# Topics: display name -> URL slug
TOPICS = {
    "Number Series": "number-series",
    "Letter and Symbol Series": "letter-and-symbol-series",
    "Verbal Classification": "verbal-classification",
    "Essential Part": "essential-part",
    "Analogies": "analogies",
    "Artificial Language": "artificial-language",
    "Matching Definitions": "matching-definitions",
    "Making Judgments": "making-judgments",
    "Verbal Reasoning": "verbal-reasoning",
    "Logical Problems": "logical-problems",
    "Logical Games": "logical-games",
    "Analyzing Arguments": "analyzing-arguments",
    "Statement and Assumption": "statement-and-assumption",
    "Course of Action": "course-of-action",
    "Statement and Conclusion": "statement-and-conclusion",
    "Theme Detection": "theme-detection",
    "Cause and Effect": "cause-and-effect",
    "Statement and Argument": "statement-and-argument",
    "Logical Deduction": "logical-deduction",
}


class IndiaBixScraper:
    def __init__(self, topic: Optional[str] = None, max_pages: int = 2, dry_run: bool = False):
        self.topic = topic
        self.max_pages = max_pages
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.stats = {"total": 0, "valid": 0, "errors": 0, "pages_processed": 0}
    
    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch page with retry logic."""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                return BeautifulSoup(response.content, "html.parser")
            except Exception as e:
                logger.warning(f"Fetch failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1 + attempt)
        return None
    
    def _extract_questions_from_page(self, soup: BeautifulSoup, topic_slug: str) -> List[Dict]:
        """Parse questions from page HTML using IndiaBix selectors."""
        rows = []
        seen_ids = set()
        
        # Questions are in divs with class 'bix-div-container'
        q_containers = soup.find_all('div', class_='bix-div-container')
        
        for container in q_containers:
            # Question text in .bix-td-qtxt
            q_elem = container.find('div', class_='bix-td-qtxt')
            if not q_elem:
                continue
            
            q_text = q_elem.get_text(strip=True)
            if not q_text or len(q_text) < 10:
                continue
            
            # Options in .bix-tbl-options → .bix-opt-row → .bix-td-option-val
            options_div = container.find('div', class_='bix-tbl-options')
            options = []
            
            if options_div:
                opt_rows = options_div.find_all('div', class_='bix-opt-row')
                for row in opt_rows:
                    opt_val_div = row.find('div', class_='bix-td-option-val')
                    if opt_val_div:
                        opt_text = opt_val_div.get_text(strip=True)
                        if opt_text and len(opt_text) < 500:
                            options.append(opt_text)
            
            if len(options) < 2:
                continue
            
            # Pad to 4 options
            while len(options) < 4:
                options.append("")
            
            # Create stable ID
            seed = f"indiabix_{topic_slug}_{q_text[:100]}"
            row_id = str(uuid5(NAMESPACE_DNS, seed))
            
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            
            rows.append({
                "id": row_id,
                "category": "gat",
                "sub_category": topic_slug,
                "text": q_text,
                "options": options[:4],
                "correct_answer_idx": 0,
                "explanation": "",
            })
        
        return rows
    
    def scrape_topic(self, topic_display: str) -> List[Dict]:
        """Scrape all pages for a topic."""
        topic_slug = TOPICS.get(topic_display, topic_display.lower().replace(" ", "-"))
        all_rows = []
        
        for page in range(1, self.max_pages + 1):
            url = BASE_URL.format(topic=topic_slug)
            if page > 1:
                url += f"page/{page}/"
            
            logger.info(f"Processing {page}/{self.max_pages}: {url}")
            soup = self._fetch_page(url)
            if not soup:
                logger.warning(f"Failed to fetch page {page}")
                self.stats["errors"] += 1
                continue
            
            rows = self._extract_questions_from_page(soup, topic_slug)
            all_rows.extend(rows)
            self.stats["pages_processed"] += 1
            logger.info(f"Extracted {len(rows)} questions from page {page}")
            
            time.sleep(REQUEST_DELAY)
        
        return all_rows
    
    def scrape_all(self) -> List[Dict]:
        """Scrape all topics or specified topic."""
        topics_to_scrape = [self.topic] if self.topic else TOPICS.keys()
        all_rows = []
        
        for topic in topics_to_scrape:
            rows = self.scrape_topic(topic)
            all_rows.extend(rows)
            self.stats["total"] += len(rows)
        
        return all_rows


def main():
    parser = argparse.ArgumentParser(description="Scrape IndiaBix logical-reasoning MCQs via HTTP.")
    parser.add_argument("--topic", default=None, help="Topic name (default: all)")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages per topic")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no upsert")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()
    
    scraper = IndiaBixScraper(topic=args.topic, max_pages=args.max_pages, dry_run=args.dry_run)
    rows = scraper.scrape_all()
    
    logger.info(f"Total questions extracted: {len(rows)}")
    
    if args.dry_run or not rows:
        if rows:
            logger.info(f"Sample row: {rows[0]}")
        return
    
    upsert_questions(rows, chunk_size=args.chunk_size)
    logger.info(f"Upserted {len(rows)} questions")


if __name__ == "__main__":
    main()
