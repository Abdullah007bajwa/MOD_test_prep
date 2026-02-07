"""
Extract Sanfoundry logical-reasoning & subject MCQs via live HTTP.
Uses div.entry-content and .collapseanswer divs for answers.
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

BASE_URL = "https://www.sanfoundry.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_DELAY = 1
MAX_RETRIES = 3

ANSWER_RE = re.compile(r"Answer\s*:\s*([a-d])", re.I)

# Logical reasoning topics (URL slug to sub_category mapping)
LOGICAL_REASONING_TOPICS = {
    "odd-man-out": "odd_man_out",
    "coding-decoding": "coding_decoding",
    "logical-deduction": "logical_deduction",
    "blood-relation": "blood_relation",
    "analogy": "analogy",
    "venn-diagram": "venn_diagram",
    "logical-sequence-words": "logical_sequence_words",
    "syllogisms": "syllogisms",
    "dot-situation-analysis": "dot_situation_analysis",
    "missing-figures": "missing_figures",
    "figure-classification": "figure_classification",
    "pattern-completion": "pattern_completion",
}

# Subject URL patterns
SUBJECT_PATTERNS = {
    "data_structures": "data-structure-questions-answers",
    "oops": "object-oriented-programming-oops-questions-answers",
    "operating_system": "operating-system-questions-answers",
    "computer_network": "computer-network-questions-answers",
}


class SanfoundryScraper:
    def __init__(self, scrape_type: str = "logical", max_sets: int = 10, dry_run: bool = False):
        """
        Args:
            scrape_type: 'logical' or 'subject'
            max_sets: Number of sets per topic (1-10)
            dry_run: Parse only, no upsert
        """
        self.scrape_type = scrape_type
        self.max_sets = max_sets
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
    
    def _parse_answer_and_explanation(self, collapse_div) -> tuple:
        """Extract (correct_answer_idx, explanation) from .collapseanswer div."""
        if not collapse_div:
            return 0, ""
        
        text = collapse_div.get_text(separator=" ", strip=True)
        
        # Parse answer
        idx = 0
        m = ANSWER_RE.search(text)
        if m:
            idx = ord(m.group(1).lower()) - ord('a')
        
        # Parse explanation
        explanation = text
        if m:
            explanation = text[m.end():].strip()
        
        return idx, explanation[:1000]
    
    def _extract_questions_from_page(self, soup: BeautifulSoup, sub_category: str) -> List[Dict]:
        """Parse questions from Sanfoundry page using .entry-content and .collapseanswer."""
        rows = []
        seen_ids = set()
        
        entry = soup.find("div", class_="entry-content")
        if not entry:
            return rows
        
        # Find all .collapseanswer divs (each has preceding question)
        collapses = entry.find_all(class_="collapseanswer")
        
        for collapse in collapses:
            correct_idx, explanation = self._parse_answer_and_explanation(collapse)
            
            # Walk backwards to find question
            prev = collapse.find_previous_sibling()
            q_text = ""
            options = []
            
            for _ in range(20):
                if not prev:
                    break
                
                block_text = prev.get_text(separator="\n", strip=True)
                lines = block_text.split("\n")
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Question: numbered like "1. "
                    if re.match(r"^\d+\.\s+", line):
                        if not q_text:
                            q_text = re.sub(r"^\d+\.\s+", "", line).strip()
                        else:
                            break
                    
                    # Option: "a. " or "a) "
                    elif re.match(r"^[a-d][\.\)]\s+", line, re.I) and "Answer" not in line:
                        options.append(line)
                        if len(options) >= 4:
                            break
                
                if q_text and len(options) >= 2:
                    break
                
                prev = prev.find_previous_sibling()
            
            if not q_text or len(q_text) < 10 or len(options) < 2:
                continue
            
            # Pad to 4 options
            while len(options) < 4:
                options.append("")
            
            if correct_idx >= len(options):
                correct_idx = 0
            
            # Create stable ID
            seed = f"sanfoundry_{sub_category}_{q_text[:100]}"
            row_id = str(uuid5(NAMESPACE_DNS, seed))
            
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            
            category = "subject" if self.scrape_type == "subject" else "gat"
            
            rows.append({
                "id": row_id,
                "category": category,
                "sub_category": sub_category,
                "text": q_text,
                "options": options[:4],
                "correct_answer_idx": correct_idx,
                "explanation": explanation,
                "source": "sanfoundry",
            })
        
        return rows
    
    def scrape_logical(self) -> List[Dict]:
        """Scrape logical reasoning questions from all topics."""
        all_rows = []
        
        for idx, (topic_slug, sub_category) in enumerate(LOGICAL_REASONING_TOPICS.items(), start=1):
            logger.info(f"\n--- Topic {idx}/{len(LOGICAL_REASONING_TOPICS)}: {topic_slug} ---")
            
            for set_num in range(1, self.max_sets + 1):
                url = f"{BASE_URL}/logical-reasoning-questions-answers-{topic_slug}-set-{set_num}/"
                logger.info(f"  Fetching set {set_num}/{self.max_sets}: {url}")
                
                soup = self._fetch_page(url)
                if not soup:
                    logger.warning(f"  Failed to fetch set {set_num}")
                    continue
                
                rows = self._extract_questions_from_page(soup, sub_category)
                all_rows.extend(rows)
                logger.info(f"    Extracted {len(rows)} questions from set {set_num}")
                
                time.sleep(REQUEST_DELAY)
            
            logger.info(f"Total from {topic_slug}: {len([r for r in all_rows if r['sub_category'] == sub_category])} questions")
            time.sleep(REQUEST_DELAY)
        
        return all_rows
    
    def scrape_subject(self) -> List[Dict]:
        """Scrape subject/CS questions."""
        all_rows = []
        
        for sub_cat, pattern in SUBJECT_PATTERNS.items():
            url = f"{BASE_URL}/{pattern}/"
            logger.info(f"Scraping subject: {sub_cat} from {url}")
            
            soup = self._fetch_page(url)
            if not soup:
                logger.warning(f"Failed to fetch {sub_cat}")
                continue
            
            rows = self._extract_questions_from_page(soup, sub_cat)
            all_rows.extend(rows)
            logger.info(f"Extracted {len(rows)} questions from {sub_cat}")
            
            time.sleep(REQUEST_DELAY)
        
        return all_rows
    
    def scrape(self) -> List[Dict]:
        """Scrape based on type."""
        if self.scrape_type == "logical":
            return self.scrape_logical()
        else:
            return self.scrape_subject()


def main():
    parser = argparse.ArgumentParser(description="Scrape Sanfoundry MCQs via HTTP.")
    parser.add_argument("--type", default="logical", help="logical or subject")
    parser.add_argument("--max-sets", type=int, default=10, help="Max sets per topic (1-10)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no upsert")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()
    
    scraper = SanfoundryScraper(scrape_type=args.type, max_sets=args.max_sets, dry_run=args.dry_run)
    rows = scraper.scrape()
    
    logger.info(f"\n\nTotal questions extracted: {len(rows)}")
    
    if args.dry_run or not rows:
        if rows:
            logger.info(f"Sample row: {rows[0]}")
        return
    
    upsert_questions(rows, chunk_size=args.chunk_size)
    logger.info(f"Upserted {len(rows)} questions")


if __name__ == "__main__":
    main()
