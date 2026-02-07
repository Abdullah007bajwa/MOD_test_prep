"""Extract Pakistan Current Affairs and GK MCQs from pakmcqs.com HAR; upsert to Supabase with deduplication."""
import argparse
import base64
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from uuid import uuid5, NAMESPACE_DNS

from bs4 import BeautifulSoup

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OPTION_LETTER_TO_IDX = {"A": 0, "B": 1, "C": 2, "D": 3}
CORRECT_ANSWER_RE = re.compile(r"Correct\s+Answer\s*:\s*([A-D])", re.I)

# URL patterns: current-affairs -> current_affairs; general-knowledge or general_knowledge -> general_knowledge
URL_CURRENT_AFFAIRS = "current-affairs"
URL_GENERAL_KNOWLEDGE_1 = "general-knowledge"
URL_GENERAL_KNOWLEDGE_2 = "general_knowledge"


def load_har(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
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
    return (
        "/category/pakistan-current-affairs-mcqs" in url
        or "/category/general-knowledge" in url
        or "/category/general_knowledge_mcqs" in url
    )


def _sub_tag_from_url(url: str) -> str:
    if URL_CURRENT_AFFAIRS in url:
        return "current_affairs"
    if URL_GENERAL_KNOWLEDGE_1 in url or URL_GENERAL_KNOWLEDGE_2 in url:
        return "general_knowledge"
    return "general_knowledge"


def iter_html_entries(har: dict):
    """Yield (url, html) for pakmcqs category HTML pages with body."""
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
            logger.warning("No response body for URL: %s", url)
            continue
        yield url, html


def _question_text_hash(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_id(question_text: str, sub_tag: str) -> str:
    h = _question_text_hash(question_text)
    return str(uuid5(NAMESPACE_DNS, f"pakmcqs_{sub_tag}_{h}"))


def _parse_correct_answer(soup_or_el) -> int:
    """Find <strong> containing 'Correct Answer:' and parse letter (A-D) -> 0-3."""
    root = soup_or_el if hasattr(soup_or_el, "find_all") else soup_or_el
    for strong in (root.find_all("strong") or []):
        t = strong.get_text(strip=True)
        m = CORRECT_ANSWER_RE.search(t)
        if m:
            return OPTION_LETTER_TO_IDX.get(m.group(1).upper(), 0)
        # Also check parent text (e.g. "Correct Answer: B" with B in strong)
        parent_text = (strong.parent.get_text() if strong.parent else "") or ""
        m = CORRECT_ANSWER_RE.search(parent_text)
        if m:
            return OPTION_LETTER_TO_IDX.get(m.group(1).upper(), 0)
    return 0


def extract_questions_from_html(html: str, url: str) -> list[dict]:
    """Parse HTML and return list of question rows (id, category, sub_category, text, options, correct_answer_idx, explanation)."""
    soup = BeautifulSoup(html, "html.parser")
    sub_tag = _sub_tag_from_url(url)
    rows = []
    seen_ids: set[str] = set()

    def add_row(block, q_text: str, options: list[str], correct_idx: int, explanation: str):
        if not q_text or len(q_text) < 10 or len(options) < 2:
            return
        q_id = _stable_id(q_text, sub_tag)
        if q_id in seen_ids:
            return
        seen_ids.add(q_id)
        while len(options) < 4:
            options.append("")
        if correct_idx >= len(options):
            correct_idx = 0
        rows.append({
            "id": q_id,
            "category": "gat",
            "sub_category": sub_tag,
            "text": q_text,
            "options": options[:4],
            "correct_answer_idx": correct_idx,
            "explanation": (explanation or "")[:50000],
        })

    # Strategy 1: Find blocks that contain <strong> Correct Answer (each = one MCQ)
    for strong in soup.find_all("strong"):
        if not CORRECT_ANSWER_RE.search(strong.get_text() or ""):
            parent_text = (strong.parent.get_text() if strong.parent else "") or ""
            if "Correct Answer" not in parent_text:
                continue
        block = strong
        for _ in range(10):
            block = block.parent
            if not block or block.name == "body":
                break
            full = block.get_text(separator="\n", strip=True)
            if "Correct Answer" not in full or len(full) < 30:
                continue
            # Question: text before first "A." or "B." or "Correct Answer"
            q_text = full
            for sep in ("A.\n", "A. ", "B.\n", "B. ", "Correct Answer", "\nCorrect Answer"):
                i = q_text.find(sep)
                if i > 15:
                    q_text = q_text[:i].strip()
                    break
            # Options: lines starting with A. B. C. D.
            options = []
            for m in re.finditer(r"^([A-D])[\.\)]\s*(.+)$", full, re.MULTILINE):
                opt_text = m.group(2).strip()
                if opt_text and "Correct Answer" not in opt_text and len(opt_text) < 400:
                    options.append(opt_text)
                    if len(options) >= 4:
                        break
            correct_idx = _parse_correct_answer(block)
            explanation = ""
            add_row(block, q_text, options, correct_idx, explanation)
            break

    # Strategy 2: .p-mcqs or [class*='mcqs'] as question block
    if not rows:
        q_blocks = soup.select(".p-mcqs") or soup.select("[class*='mcqs']") or soup.select(".entry-content div")
        for block in q_blocks:
            q_el = block.select_one(".p-mcqs") or block
            q_text = (q_el.get_text(separator=" ", strip=True) if q_el else "") or block.get_text(separator=" ", strip=True)
            for marker in ("Correct Answer", "A.", "B."):
                i = q_text.find(marker)
                if i > 20:
                    q_text = q_text[:i].strip()
                    break
            if not q_text or len(q_text) < 10:
                continue
            options = []
            for opt in block.select("li, p"):
                t = opt.get_text(separator=" ", strip=True)
                if re.match(r"^[A-D][\.\)]\s*", t) and "Correct Answer" not in t and len(t) < 400:
                    options.append(t)
            if not options:
                for m in re.finditer(r"[A-D][\.\)]\s*([^\n]+)", block.get_text(separator="\n")):
                    options.append(m.group(1).strip())
                    if len(options) >= 4:
                        break
            correct_idx = _parse_correct_answer(block)
            expl_el = block.find("strong", string=re.compile(r"Explanation", re.I))
            explanation = (expl_el.parent.get_text(separator=" ", strip=True) if expl_el and expl_el.parent else "") or ""
            add_row(block, q_text, options, correct_idx, explanation)

    return rows


def parse_har_to_questions(har_path: Path) -> list[dict]:
    har = load_har(har_path)
    all_rows = []
    entries = list(iter_html_entries(har))
    total = len(entries)
    logger.info("Found %d matching HTML entries", total)
    for idx, (url, html) in enumerate(entries, start=1):
        if total:
            logger.info("Processing %d/%d: %s", idx, total, url)
        rows = extract_questions_from_html(html, url)
        all_rows.extend(rows)
        logger.info("URL %s: extracted %d questions", url, len(rows))
    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Extract pakmcqs.com Current Affairs / GK from HAR and upsert to Supabase.")
    parser.add_argument("har", nargs="?", type=Path, default=_root / "pakmcqs.com.har", help="Path to .har file")
    parser.add_argument("--dry-run", action="store_true", help="Do not upsert; only parse and report")
    parser.add_argument("--out", type=Path, default=None, help="Write extracted questions to JSON file")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()

    if not args.har.exists():
        logger.error("HAR file not found: %s", args.har)
        sys.exit(1)

    rows = parse_har_to_questions(args.har)
    logger.info("Total questions extracted: %d", len(rows))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        logger.info("Wrote %s", args.out)

    if args.dry_run:
        if rows:
            logger.info("Sample row keys: %s", list(rows[0].keys()))
        return

    if not rows:
        logger.warning("No questions to upsert.")
        return

    upsert_questions(rows, chunk_size=args.chunk_size)
    logger.info("Upserted %d questions (duplicates overwritten by stable id from question hash).", len(rows))


if __name__ == "__main__":
    main()
