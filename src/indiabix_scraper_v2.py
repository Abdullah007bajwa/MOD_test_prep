"""
Extract IndiaBIX Logical Reasoning MCQs via live HTTP.
Strategy: 
1. Fetch category listing page (e.g., /logical-reasoning/logical-problems/)
2. Extract all question type URLs (Type 1, Type 2, etc.)
3. Fetch each type page to extract individual question URLs
4. Fetch each individual question and parse
"""
import argparse
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Set
from uuid import uuid5, NAMESPACE_DNS

import requests
from bs4 import BeautifulSoup

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.indiabix.com/logical-reasoning"

TOPICS = {
    "number-series": "Number Series",
    "letter-and-symbol-series": "Letter and Symbol Series",
    "verbal-classification": "Verbal Classification",
    "essential-part": "Essential Part",
    "analogies": "Analogies",
    "artificial-language": "Artificial Language",
    "matching-definitions": "Matching Definitions",
    "making-judgments": "Making Judgments",
    "verbal-reasoning": "Verbal Reasoning",
    "logical-problems": "Logical Problems",
    "logical-games": "Logical Games",
    "analyzing-arguments": "Analyzing Arguments",
    "statement-and-assumption": "Statement and Assumption",
    "course-of-action": "Course of Action",
    "statement-and-conclusion": "Statement and Conclusion",
    "theme-detection": "Theme Detection",
    "cause-and-effect": "Cause and Effect",
    "statement-and-argument": "Statement and Argument",
    "logical-deduction": "Logical Deduction",
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_DELAY = 0.5
MAX_RETRIES = 3


def _fetch_page(url: str) -> Optional[str]:
    """Fetch page with retry logic."""
    for attempt in range(MAX_RETRIES):
        try:
            headers = {"User-Agent": USER_AGENT}
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.text
            logger.warning(f"Status {response.status_code} for {url}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed for {url}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    return None


def _question_text_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_id(question_text: str) -> str:
    h = _question_text_hash(question_text)
    return str(uuid5(NAMESPACE_DNS, f"indiabix_{h}"))


def extract_question_urls_from_category_page(topic_slug: str, max_questions: int = 100) -> Set[str]:
    """
    Fetch category page and extract starting URLs, normalized to page 001 of each type.
    IndiaBIX organizes questions into Types (e.g., 001001, 001002... or 002001, 002002...).
    Category page may show any page from a type, so we normalize to XXX001.
    """
    category_url = f"{BASE_URL}/{topic_slug}/"
    
    logger.info(f"  Fetching category page: {category_url}")
    html = _fetch_page(category_url)
    if not html:
        logger.warning(f"Failed to fetch category page")
        return set()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Extract all question IDs and group by type (first 3 digits)
    pattern = re.compile(f"{re.escape(topic_slug)}/(\d{{6}})")
    types_found = set()
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        match = pattern.search(href)
        if match:
            question_id = match.group(1)
            # Extract type (first 3 digits) and normalize to page 001
            type_prefix = question_id[:3]
            types_found.add(type_prefix)
    
    # Build starting URLs (XXX001 for each type)
    starting_urls = set()
    for type_prefix in types_found:
        start_id = f"{type_prefix}001"
        start_url = f"https://www.indiabix.com/logical-reasoning/{topic_slug}/{start_id}"
        starting_urls.add(start_url)
    
    logger.info(f"    Found {len(starting_urls)} types, starting from page 001 of each")
    return starting_urls


def extract_questions_from_page(url: str, topic_slug: str) -> List[Dict]:
    """Extract single question from its dedicated page, including answer from collapsed div."""
    time.sleep(REQUEST_DELAY)
    
    html = _fetch_page(url)
    if not html:
        return None
    
    soup = BeautifulSoup(html, 'html.parser')
    
    try:
        # Find ALL question containers on the page (1-6 questions per page)
        question_divs = soup.find_all('div', class_='bix-div-container')
        questions = []
        
        for question_div in question_divs:
        
            # Extract question text
            q_text_el = question_div.select_one('.bix-td-qtxt')
            if not q_text_el:
                continue
        
            q_text = q_text_el.get_text(separator=' ', strip=True)
            if len(q_text) < 10:
                continue
        
            # Extract options
            options = []
            for opt_row in question_div.select('.bix-opt-row'):
                opt_text = opt_row.get_text(separator=' ', strip=True)
                if opt_text:
                    options.append(opt_text)
            
            if len(options) < 3:
                continue
        
            # Pad to 4 options
            while len(options) < 4:
                options.append("")
            options = options[:4]
            
            # Extract answer and explanation
            answer_idx = 0
            explanation = ""
        
            answer_div = question_div.find_next('div', class_='bix-div-answer')
            if answer_div:
                option_span = answer_div.find('span', class_=lambda x: x and 'option-svg-letter' in x)
                if option_span:
                    class_str = ' '.join(option_span.get('class', []))
                    match = re.search(r'option-svg-letter-([a-d])', class_str)
                    if match:
                        answer_letter = match.group(1).lower()
                        answer_idx = ord(answer_letter) - ord('a')
                
                text = answer_div.get_text()
                if 'Explanation:' in text:
                    parts = text.split('Explanation:', 1)
                    explanation = parts[1].strip() if len(parts) > 1 else ""
        
            q_id = _stable_id(q_text)
            
            questions.append({
                "id": q_id,
                "category": "gat",
                "sub_category": topic_slug.replace("-", "_"),
                "text": q_text,
                "options": options,
                "correct_answer_idx": answer_idx,
                "explanation": explanation,
                "source": "indiabix"
            })
        
        # Extract Next page link (after processing all questions)
        next_url = None
        for link in soup.find_all('a', href=True):
            if 'Next' in link.get_text():
                href = link.get('href', '')
                if href and href != '#' and topic_slug in href:
                    next_url = href if href.startswith('http') else f"https://www.indiabix.com{href}"
                    break
        
        return questions, next_url
    
    except Exception as e:
        logger.error(f"Error parsing {url}: {e}")
        return [], None


def scrape_topic(topic_slug: str, max_questions: int = 100) -> List[Dict]:
    """Scrape questions for a topic by following page pagination within each type."""
    questions = []
    seen_ids: Set[str] = set()
    
    logger.info(f"\nProcessing topic: {topic_slug}")
    
    # Get all starting question URLs (one per type/section)
    starting_urls = extract_question_urls_from_category_page(topic_slug, max_questions)
    
    if not starting_urls:
        logger.warning(f"No starting questions found for {topic_slug}")
        return questions
    
    # Process each type's pages
    for type_idx, start_url in enumerate(starting_urls, 1):
        if len(questions) >= max_questions:
            break
            
        logger.info(f"  Processing type {type_idx}/{len(starting_urls)}: {start_url}")
        current_url = start_url
        type_count = 0
        pages_without_question = 0
        
        # Follow page pagination within this type (each page has 1-6 questions)
        while current_url and len(questions) < max_questions and pages_without_question < 2:
            page_questions, next_url = extract_questions_from_page(current_url, topic_slug)
            
            if page_questions:
                for question in page_questions:
                    q_id = question["id"]
                    if q_id not in seen_ids and len(questions) < max_questions:
                        seen_ids.add(q_id)
                        questions.append(question)
                        type_count += 1
                
                pages_without_question = 0
                current_url = next_url
            else:
                pages_without_question += 1
                if pages_without_question < 2 and next_url:
                    current_url = next_url
                else:
                    break
        
        logger.info(f"    Extracted {type_count} questions from type {type_idx}")
    
    logger.info(f"Extracted {len(questions)} total questions from {topic_slug}")
    return questions


def main():
    parser = argparse.ArgumentParser(description="Extract IndiaBIX logical reasoning questions via live HTTP.")
    parser.add_argument("--max-questions", type=int, default=100, help="Max questions per topic")
    parser.add_argument("--max-topics", type=int, default=len(TOPICS), help="Max topics to process")
    parser.add_argument("--dry-run", action="store_true", help="Do not upsert; only parse and report")
    parser.add_argument("--out", type=Path, default=None, help="Write extracted questions to JSON")
    parser.add_argument("--backup-json", action="store_true", help="Auto-save to data/indiabix_backup_TIMESTAMP.json")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()
    
    all_questions = []
    
    # Scrape each topic
    for idx, (topic_slug, topic_name) in enumerate(TOPICS.items(), start=1):
        if idx > args.max_topics:
            break
        
        logger.info(f"\n--- Topic {idx}/{min(args.max_topics, len(TOPICS))}: {topic_name} ---")
        
        questions = scrape_topic(topic_slug, max_questions=args.max_questions)
        all_questions.extend(questions)
        
        # Respect rate limits between topics
        time.sleep(0.5)
    
    logger.info(f"\n\nTotal questions extracted: {len(all_questions)}")
    
    # Auto-backup if requested
    if args.backup_json and all_questions:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path("data")
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"indiabix_backup_{timestamp}.json"
        with backup_path.open("w", encoding="utf-8") as f:
            json.dump(all_questions, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Backup saved: {backup_path}")
    
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            json.dump(all_questions, f, indent=2, ensure_ascii=False)
        logger.info(f"Wrote {args.out}")
    
    if args.dry_run:
        if all_questions:
            logger.info(f"Sample question: {all_questions[0]}")
        return
    
    if not all_questions:
        logger.warning("No questions to upsert")
        return
    
    upsert_questions(all_questions, chunk_size=args.chunk_size)
    logger.info(f"Upserted {len(all_questions)} IndiaBIX questions to Supabase")


if __name__ == "__main__":
    main()
