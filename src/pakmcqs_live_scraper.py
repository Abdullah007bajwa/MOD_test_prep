"""
Extract PakMCQs.com current affairs & general knowledge MCQs via live HTTP.
Maps to gat category with sub_category: current_affairs or general_knowledge.
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict
import re
from uuid import uuid5, NAMESPACE_DNS

import requests
from bs4 import BeautifulSoup

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URLS = {
    "current_affairs": "https://pakmcqs.com/category/pakistan-current-affairs-mcqs/",
    "general_knowledge": "https://pakmcqs.com/category/general_knowledge_mcqs/",
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_DELAY = 1
MAX_RETRIES = 3

ANSWER_RE = re.compile(r"Correct\s+Answer\s*:\s*([A-D])", re.I)


class PakMCQsScraper:
    def __init__(self, category: Optional[str] = None, max_pages: int = 3, dry_run: bool = False):
        self.category = category or "general_knowledge"
        self.max_pages = max_pages
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.stats = {"total": 0, "valid": 0, "errors": 0}
    
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
    
    def _parse_correct_answer(self, text: str) -> int:
        """Extract correct answer index (A-D -> 0-3) from text."""
        m = ANSWER_RE.search(text)
        if m:
            letter = m.group(1).upper()
            return ord(letter) - ord('A')
        return 0
    
    def _extract_questions_from_page(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse questions from page HTML."""
        rows = []
        seen_ids = set()
        
        # PakMCQs uses <article class="l-post"> for each MCQ or grouped questions
        articles = soup.find_all("article", class_=lambda x: x and "post" in str(x).lower())
        
        for article in articles:
            # Title is typically in <h2 class="post-title">
            title_elem = article.find("h2", class_="post-title")
            if not title_elem:
                continue
            
            # Get question text from title or content
            q_text = title_elem.get_text(strip=True)
            if not q_text or len(q_text) < 5:
                continue
            
            # Look for options in the article content
            content_div = article.find("div", class_="content") or article
            full_text = content_div.get_text(separator="\n", strip=True)
            
            # Extract options (A. B. C. D. patterns)
            options = []
            for m in re.finditer(r"^([A-D])[\.\)]\s*(.+)$", full_text, re.MULTILINE):
                opt_text = m.group(2).strip()
                if opt_text and "Correct Answer" not in opt_text and len(opt_text) < 300:
                    options.append(opt_text)
                if len(options) >= 4:
                    break
            
            if len(options) < 2:
                continue
            
            # Pad to 4
            while len(options) < 4:
                options.append("")
            
            # Parse answer
            correct_idx = self._parse_correct_answer(full_text)
            
            # Create stable ID using question text + options (more unique)
            seed = f"pakmcqs_{self.category}_{q_text}_{options[0]}_{options[1]}"
            row_id = str(uuid5(NAMESPACE_DNS, seed))
            
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            
            rows.append({
                "id": row_id,
                "category": "gat",
                "sub_category": self.category,
                "text": q_text,
                "options": options[:4],
                "correct_answer_idx": correct_idx,
                "explanation": "",
                "source": "pakmcqs",
            })
        
        return rows
    
    def scrape(self) -> List[Dict]:
        """Scrape all pages for the category."""
        base_url = BASE_URLS.get(self.category, BASE_URLS["general_knowledge"])
        all_rows = []
        
        for page in range(1, self.max_pages + 1):
            url = base_url if page == 1 else f"{base_url}page/{page}/"
            logger.info(f"Fetching {self.category} page {page}: {url}")
            
            soup = self._fetch_page(url)
            if not soup:
                logger.warning(f"Failed to fetch page {page}")
                self.stats["errors"] += 1
                continue
            
            rows = self._extract_questions_from_page(soup)
            all_rows.extend(rows)
            logger.info(f"Extracted {len(rows)} questions from page {page}")
            
            time.sleep(REQUEST_DELAY)
        
        self.stats["total"] = len(all_rows)
        return all_rows


def main():
    parser = argparse.ArgumentParser(description="Scrape PakMCQs.com via HTTP.")
    parser.add_argument("--category", default="general_knowledge", help="current_affairs or general_knowledge")
    parser.add_argument("--max-pages", type=int, default=3, help="Max pages")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no upsert")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()
    
    scraper = PakMCQsScraper(category=args.category, max_pages=args.max_pages, dry_run=args.dry_run)
    rows = scraper.scrape()
    
    logger.info(f"Total questions extracted: {len(rows)}")
    
    if args.dry_run or not rows:
        if rows:
            logger.info(f"Sample row keys: {list(rows[0].keys())}")
        return
    
    upsert_questions(rows, chunk_size=args.chunk_size)
    logger.info(f"Upserted {len(rows)} questions")


if __name__ == "__main__":
    main()
