"""Extract Sanfoundry Logical Reasoning MCQs from HAR. category='gat', sub_category from URL slug."""
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
ANSWER_RE = re.compile(r"Answer\s*:\s*([a-d])", re.I)
EXPLANATION_RE = re.compile(r"Explanation\s*:\s*(.+?)(?=\n\d+\.|$)", re.I | re.DOTALL)

# Target: logical-reasoning URLs in HAR
LOGICAL_REASONING_PATTERN = "logical-reasoning-questions-answers"

SKIP_PHRASES = (
    "advertisement",
    "Free Certifications",
    "Recommended Articles",
    "YouTube MasterClass",
    "founder",
    "Sanfoundry Global Education",
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
    """Match logical-reasoning URLs (exclude images)."""
    if "sanfoundry.com" not in url:
        return False
    if LOGICAL_REASONING_PATTERN not in url:
        return False
    if url.endswith((".png", ".jpg", ".jpeg", ".gif", ".css", ".js")):
        return False
    return True


def _sub_tag_from_url(url: str) -> str:
    """Derive sub_tag from URL (e.g. coding_decoding, number_series)."""
    path = (url.split("sanfoundry.com")[-1].split("?")[0] or "").strip("/")
    # Extract slug between "logical-reasoning-questions-answers" and any "set-N"
    # Example: logical-reasoning-questions-answers-coding-decoding-set-5 -> coding-decoding
    match = re.search(r"logical-reasoning-questions-answers-(.+?)(?:-set-\d+)?/?$", path)
    if match:
        slug = match.group(1).replace("-", "_")
        return slug
    return "logical_reasoning"


def _question_text_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_id(question_text: str) -> str:
    """Stable id from question text only so same question across different sets = one row (dedup)."""
    h = _question_text_hash(question_text)
    return str(uuid5(NAMESPACE_DNS, f"sanfoundry_logical_{h}"))


def _is_noise(text: str) -> bool:
    t = (text or "").lower()
    return any(phrase.lower() in t for phrase in SKIP_PHRASES)


def _parse_answer_from_paragraph(paragraph_text: str) -> tuple[int, str]:
    """Extract Answer and Explanation from paragraph text. Returns (correct_idx, explanation)."""
    correct_idx = -1
    explanation = ""
    
    # Find Answer: x
    m = ANSWER_RE.search(paragraph_text)
    if m:
        correct_idx = OPTION_LETTER_TO_IDX.get(m.group(1).lower(), 0)
    
    # Find Explanation: ...
    em = EXPLANATION_RE.search(paragraph_text)
    if em:
        explanation = em.group(1).strip()[:5000]
    
    return correct_idx, explanation


def extract_questions_from_html(html: str, url: str) -> list[dict]:
    """Parse .entry-content: numbered questions with options (a–d), then Answer + Explanation.
    Questions are in <p> tags, inline with answer/explanation."""
    soup = BeautifulSoup(html, "html.parser")
    sub_tag = _sub_tag_from_url(url)
    rows = []
    seen_ids: set[str] = set()

    entry = soup.select_one(".entry-content")
    if not entry:
        return rows

    # Remove noise sections
    for node in list(entry.find_all(string=re.compile("|".join(re.escape(p) for p in SKIP_PHRASES), re.I))):
        parent = node.parent
        if parent and parent.name in ("div", "p", "section", "aside"):
            try:
                parent.decompose()
            except:
                pass

    paragraphs = entry.find_all("p")
    for p in paragraphs:
        text = p.get_text(separator="\n", strip=True)
        
        # Skip empty or noise
        if not text or len(text) < 15 or _is_noise(text):
            continue
        
        # Skip non-question paragraphs (must start with number)
        if not re.match(r"^\d+\.\s+", text):
            continue
        
        lines = text.split("\n")
        q_text = ""
        options = []
        answer_idx = -1
        explanation = ""
        
        # Parse lines
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Question line (numbered)
            if re.match(r"^\d+\.\s+", line):
                if not q_text:
                    q_text = re.sub(r"^\d+\.\s+", "", line).strip()
                else:
                    q_text += " " + re.sub(r"^\d+\.\s+", "", line).strip()
            
            # Option line (a) b) c) d)
            elif re.match(r"^[a-d]\s*[\.\)]\s+", line, re.I):
                # Clean up option
                opt = re.sub(r"^[a-d]\s*[\.\)]\s*", "", line, flags=re.I).strip()
                if opt and "Answer" not in opt and "Explanation" not in opt:
                    options.append(opt)
            
            # Answer line
            elif "Answer" in line and ANSWER_RE.search(line):
                m = ANSWER_RE.search(line)
                if m:
                    answer_idx = OPTION_LETTER_TO_IDX.get(m.group(1).lower(), 0)
            
            # Explanation line
            elif "Explanation" in line:
                # Grab rest of text from Explanation onwards
                explanation = line
                em = EXPLANATION_RE.search(explanation)
                if em:
                    explanation = em.group(1).strip()[:5000]
                break
            
            # Continue building question if not yet options
            elif not options and not re.match(r"^[a-d]\s*[\.\)]\s+", line, re.I):
                if q_text:
                    q_text += " " + line
        
        # Also try to extract answer/explanation from full paragraph text
        if answer_idx < 0 or not explanation:
            full_text = p.get_text(separator=" ", strip=True)
            idx, expl = _parse_answer_from_paragraph(full_text)
            if answer_idx < 0:
                answer_idx = idx
            if not explanation:
                explanation = expl
        
        # Validate
        if not q_text or len(q_text) < 10 or len(options) < 3 or answer_idx < 0 or not explanation or len(explanation) < 10:
            continue
        
        # Pad options
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
            "explanation": explanation,
            "source": "sanfoundry",
        })
    
    return rows


def iter_html_entries(har: dict):
    """Yield (url, html) for logical-reasoning URLs with body content."""
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
    logger.info("Found %d matching logical-reasoning HTML entries", total)
    for idx, (url, html) in enumerate(entries, start=1):
        if total:
            logger.info("Processing %d/%d: %s", idx, total, url)
        rows = extract_questions_from_html(html, url)
        all_rows.extend(rows)
        logger.info("  Extracted %d questions from this page", len(rows))
    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Extract Sanfoundry Logical Reasoning MCQs from HAR; upsert to Supabase.")
    parser.add_argument("har", nargs="?", type=Path, default=_root / "www.sanfoundry.com.har", help="Path to .har file")
    parser.add_argument("--dry-run", action="store_true", help="Do not upsert; only parse and report")
    parser.add_argument("--out", type=Path, default=None, help="Write extracted questions to JSON file")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()

    if not args.har.exists():
        logger.error("HAR file not found: %s", args.har)
        sys.exit(1)

    rows = parse_har_to_questions(args.har)
    logger.info("Total questions extracted: %d (category=gat, logical reasoning, deduplicated by question text)", len(rows))

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
    logger.info("Upserted %d logical-reasoning questions.", len(rows))


if __name__ == "__main__":
    main()
