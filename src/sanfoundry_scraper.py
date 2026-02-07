"""Extract Sanfoundry logical-reasoning MCQs from HAR; upsert to Supabase with deduplication."""
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

OPTION_LETTER_TO_IDX = {"a": 0, "b": 1, "c": 2, "d": 3}
ANSWER_RE = re.compile(r"Answer\s*:\s*([a-d])", re.I)

# Noise phrases: skip blocks containing these (advertisement, Free Certifications, Recommended Articles, footer)
SKIP_PHRASES = (
    "advertisement",
    "Free Certifications",
    "Recommended Articles",
    "YouTube MasterClass",
    "founder",
    "Sanfoundry Global Education",
)


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
    return "sanfoundry.com/logical-reasoning-questions-answers" in url


def _sub_tag_from_url(url: str) -> str:
    """Extract slug after logical-reasoning-questions-answers-; e.g. coding-decoding-set-3 -> coding_decoding_set_3."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/")
        prefix = "logical-reasoning-questions-answers"
        if path == prefix or path == prefix + "/":
            return "logical_reasoning"
        if prefix + "-" in path:
            slug = path.split(prefix + "-", 1)[-1].rstrip("/")
            return slug.replace("-", "_") if slug else "logical_reasoning"
        return "logical_reasoning"
    except Exception:
        return "logical_reasoning"


def iter_html_entries(har: dict):
    """Yield (url, html) for Sanfoundry logical-reasoning HTML pages with body."""
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
    return str(uuid5(NAMESPACE_DNS, f"sanfoundry_{sub_tag}_{h}"))


def _is_noise(text: str) -> bool:
    t = (text or "").lower()
    return any(phrase.lower() in t for phrase in SKIP_PHRASES)


def _parse_correct_and_explanation(collapse_div) -> tuple[int, str]:
    """From .collapseanswer div: (correct_answer_idx, explanation)."""
    if not collapse_div:
        return 0, ""
    text = collapse_div.get_text(separator=" ", strip=True)
    idx = 0
    m = ANSWER_RE.search(text)
    if m:
        idx = OPTION_LETTER_TO_IDX.get(m.group(1).lower(), 0)
    # Explanation: rest of text after "Answer: x" or first paragraph after answer
    explanation = text
    if m:
        explanation = text[m.end() :].strip()
    explanation = explanation[:50000]
    return idx, explanation


def extract_questions_from_html(html: str, url: str) -> list[dict]:
    """Parse .entry-content: numbered questions (1., 2., …), options (a–d), subsequent .collapseanswer for answer and explanation."""
    soup = BeautifulSoup(html, "html.parser")
    sub_tag = _sub_tag_from_url(url)
    rows = []
    seen_ids: set[str] = set()

    entry = soup.select_one(".entry-content")
    if not entry:
        return rows

    # Strip noise: remove nodes that are clearly ads/links/footer
    for node in list(entry.find_all(string=re.compile("|".join(re.escape(p) for p in SKIP_PHRASES), re.I))):
        parent = node.parent
        if parent and parent.name in ("div", "p", "section", "aside") and parent in entry.descendants:
            parent.decompose()

    # DOM-based: find each .collapseanswer; its preceding question is the block before it (numbered 1., 2., … with a. b. c. d.)
    collapse_divs = entry.select(".collapseanswer")
    for collapse in collapse_divs:
        correct_idx, explanation = _parse_correct_and_explanation(collapse)
        # Preceding question block: walk backwards to find element(s) that contain "N. " and options a. b. c. d.
        prev = collapse.find_previous_sibling()
        q_text = ""
        options = []
        collected = []
        for _ in range(15):
            if not prev:
                break
            t = prev.get_text(separator="\n", strip=True)
            if _is_noise(t):
                prev = prev.find_previous_sibling()
                continue
            collected.append((prev, t))
            prev = prev.find_previous_sibling()
        collected.reverse()
        for _el, block_text in collected:
            lines = block_text.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^\d+\.\s+", line) and not q_text:
                    q_text = re.sub(r"^\d+\.\s+", "", line).strip()
                elif re.match(r"^\d+\.\s+", line) and q_text:
                    q_text += " " + re.sub(r"^\d+\.\s+", "", line).strip()
                elif re.match(r"^[a-d][\.\)]\s+", line, re.I) and "Answer" not in line:
                    options.append(line)
                elif q_text and not re.match(r"^[a-d][\.\)]\s+", line, re.I) and "Answer" not in line and not re.match(r"^\d+\.\s+", line):
                    q_text += " " + line
            if q_text and len(options) >= 2:
                break
        if not q_text or len(q_text) < 10 or len(options) < 2:
            continue
        while len(options) < 4:
            options.append("")
        q_id = _stable_id(q_text, sub_tag)
        if q_id in seen_ids:
            continue
        seen_ids.add(q_id)
        rows.append({
            "id": q_id,
            "category": "gat",
            "sub_category": sub_tag,
            "text": q_text,
            "options": options[:4],
            "correct_answer_idx": correct_idx,
            "explanation": explanation[:50000],
        })

    # If no collapseanswer divs, fallback: find numbered blocks (1., 2., …) and collect options from following siblings
    if not rows:
        for el in entry.find_all(["p", "div"]):
            t = el.get_text(separator=" ", strip=True)
            if not re.match(r"^\d+\.\s+", t) or _is_noise(t) or len(t) < 20:
                continue
            q_text = re.sub(r"^\d+\.\s+", "", t).strip()
            options = []
            next_el = el.find_next_sibling()
            for _ in range(8):
                if not next_el:
                    break
                block_text = next_el.get_text(separator=" ", strip=True)
                if _is_noise(block_text):
                    next_el = next_el.find_next_sibling()
                    continue
                if re.match(r"^[a-d][\.\)]\s*", block_text, re.I):
                    options.append(block_text)
                    if len(options) >= 4:
                        break
                if re.match(r"^\d+\.\s+", block_text) or "collapseanswer" in (next_el.get("class") or []):
                    break
                next_el = next_el.find_next_sibling()
            collapse = el.find_next(class_=re.compile(r"collapseanswer", re.I))
            correct_idx, explanation = _parse_correct_and_explanation(collapse)
            while len(options) < 4:
                options.append("")
            q_id = _stable_id(q_text, sub_tag)
            if q_id not in seen_ids and len(q_text) > 10 and len(options) >= 2:
                seen_ids.add(q_id)
                rows.append({
                    "id": q_id,
                    "category": "gat",
                    "sub_category": sub_tag,
                    "text": q_text,
                    "options": options[:4],
                    "correct_answer_idx": correct_idx,
                    "explanation": explanation[:50000],
                })

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
    parser = argparse.ArgumentParser(description="Extract Sanfoundry logical-reasoning MCQs from HAR and upsert to Supabase.")
    parser.add_argument("har", nargs="?", type=Path, default=_root / "www.sanfoundry.com.har", help="Path to .har file")
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
