"""Extract PakMCQs Current Affairs and General Knowledge MCQs from HAR. category='gat', sub_category from URL."""
import argparse
import base64
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from uuid import uuid5, NAMESPACE_DNS

from bs4 import BeautifulSoup

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OPTION_LETTER_TO_IDX = {"a": 0, "b": 1, "c": 2, "d": 3}

# Target category URLs
CURRENT_AFFAIRS_PATTERN = "pakistan-current-affairs-mcqs"
GENERAL_KNOWLEDGE_PATTERN = "general_knowledge_mcqs"

SKIP_PHRASES = (
    "Submitted by:",
    "Read More Details",
    "View More",
    "YouTube",
)


def load_har(path: Path) -> dict:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return json.load(f)


def _get_html_from_content(content: dict) -> str | None:
    text = content.get("text")
    if text is None:
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning("Failed to decode base64 content: %s", e)
            return None
    return text if isinstance(text, str) else None


def _is_html_response(entry: dict) -> bool:
    resp = entry.get("response") or {}
    for h in resp.get("headers") or []:
        if (h.get("name") or "").lower() == "content-type":
            return "text/html" in (h.get("value") or "").lower()
    return False


def _url_matches(url: str) -> bool:
    """Match pakmcqs.com current affairs or general knowledge category URLs."""
    if "pakmcqs.com" not in url:
        return False
    if CURRENT_AFFAIRS_PATTERN in url or GENERAL_KNOWLEDGE_PATTERN in url:
        return True
    return False


def _sub_tag_from_url(url: str) -> str:
    """Derive sub_tag from URL."""
    if CURRENT_AFFAIRS_PATTERN in url:
        return "current_affairs"
    if GENERAL_KNOWLEDGE_PATTERN in url:
        return "general_knowledge"
    return "gat"


def _question_text_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_id(question_text: str) -> str:
    """Stable id from question text."""
    h = _question_text_hash(question_text)
    return str(uuid5(NAMESPACE_DNS, f"pakmcqs_{h}"))


def _is_noise(text: str) -> bool:
    t = (text or "").lower()
    return any(phrase.lower() in t for phrase in SKIP_PHRASES)


def extract_questions_from_html(html: str, url: str) -> list[dict]:
    """Parse pakmcqs HTML: extract questions from <article class='l-post'> elements.
    First <strong> tag contains the correct answer (e.g., 'C. Option Text')."""
    soup = BeautifulSoup(html, "html.parser")
    sub_tag = _sub_tag_from_url(url)
    rows = []
    seen_ids: set[str] = set()

    articles = soup.find_all("article", class_="l-post")
    
    for article in articles:
        lines = article.get_text(separator="\n", strip=True).split("\n")
        
        # Skip if too short
        if len(lines) < 6:
            continue
        
        # Question is first line
        q_text = lines[0].strip()
        if not q_text or len(q_text) < 10:
            continue
        
        # Extract options (lines starting with A., B., C., D.)
        options = []
        answer_idx = -1
        
        for line in lines:
            line = line.strip()
            if not line or _is_noise(line):
                continue
            
            # Option line (A., B., C., D.)
            if re.match(r"^[A-D]\.\s+", line):
                options.append(line)
        
        # Extract answer from first <strong> tag
        strong = article.find("strong")
        if strong:
            strong_text = strong.get_text().strip()
            # Expected format: "A. Option Text" or "B. Option Text", etc.
            m = re.match(r"^([A-D])\.\s+", strong_text)
            if m:
                answer_letter = m.group(1).upper()
                answer_idx = OPTION_LETTER_TO_IDX.get(answer_letter.lower(), 0)
        
        # Validate
        if not q_text or len(q_text) < 10 or len(options) < 3 or answer_idx < 0:
            continue
        
        # Pad options to 4
        while len(options) < 4:
            options.append("")
        options = options[:4]
        
        if answer_idx >= len(options):
            answer_idx = 0
        
        q_id = _stable_id(q_text)
        if q_id in seen_ids:
            continue
        seen_ids.add(q_id)
        
        rows.append({
            "id": q_id,
            "category": "gat",
            "sub_category": sub_tag,
            "text": q_text,
            "options": options,
            "correct_answer_idx": answer_idx,
            "explanation": "",  # PakMCQs doesn't provide explanations in HAR
        })
    
    return rows


def iter_html_entries(har: dict):
    """Yield (url, html) for pakmcqs current affairs and general knowledge category pages."""
    entries = har.get("log", {}).get("entries") or []
    for entry in entries:
        req = entry.get("request") or {}
        url = (req.get("url") or "").strip()
        if not _url_matches(url):
            continue
        resp = entry.get("response") or {}
        if resp.get("status") != 200:
            continue
        if not _is_html_response(entry):
            continue
        content = resp.get("content") or {}
        html = _get_html_from_content(content)
        if not html:
            continue
        yield url, html


def parse_har_to_questions(har_path: Path) -> list[dict]:
    har = load_har(har_path)
    all_rows = []
    entries = list(iter_html_entries(har))
    total = len(entries)
    logger.info("Found %d matching pakmcqs category HTML entries", total)
    for idx, (url, html) in enumerate(entries, start=1):
        if total:
            logger.info("Processing %d/%d: %s", idx, total, url)
        rows = extract_questions_from_html(html, url)
        all_rows.extend(rows)
        logger.info("  Extracted %d questions from this page", len(rows))
    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Extract PakMCQs Current Affairs and GK MCQs from HAR; upsert to Supabase.")
    parser.add_argument("har", nargs="?", type=Path, default=_root / "pakmcqs.com.har", help="Path to .har file")
    parser.add_argument("--dry-run", action="store_true", help="Do not upsert; only parse and report")
    parser.add_argument("--out", type=Path, default=None, help="Write extracted questions to JSON file")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()

    if not args.har.exists():
        logger.error("HAR file not found: %s", args.har)
        sys.exit(1)

    rows = parse_har_to_questions(args.har)
    logger.info("Total questions extracted: %d (category=gat, current_affairs/general_knowledge)", len(rows))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        logger.info("Wrote %s", args.out)

    if args.dry_run:
        if rows:
            logger.info("Sample row: %s", rows[0])
        return

    if not rows:
        logger.warning("No questions to upsert.")
        return

    upsert_questions(rows, chunk_size=args.chunk_size)
    logger.info("Upserted %d pakmcqs questions (current affairs and general knowledge).", len(rows))


if __name__ == "__main__":
    main()
