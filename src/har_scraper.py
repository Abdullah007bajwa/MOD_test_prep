"""Extract IndiaBix logical-reasoning MCQs from a HAR file; output rows for Supabase questions table."""
import argparse
import base64
import json
import logging
import re
import sys
from pathlib import Path
from uuid import uuid5, NAMESPACE_DNS

from bs4 import BeautifulSoup

# Repo root on path for db_manager
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OPTION_LETTER_TO_IDX = {"A": 0, "B": 1, "C": 2, "D": 3}
ANSWER_OPTION_RE = re.compile(r"Answer:\s*Option\s*([A-D])", re.I)
EXPLANATION_RE = re.compile(r"Explanation\s*:\s*(.+)", re.I | re.DOTALL)


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
    headers = resp.get("headers") or []
    for h in headers:
        if h.get("name", "").lower() == "content-type":
            ct = (h.get("value") or "").lower()
            return "text/html" in ct
    return False


def iter_html_entries(har: dict):
    """Yield (url, html) for entries that are logical-reasoning HTML pages with body."""
    entries = har.get("log", {}).get("entries") or []
    for entry in entries:
        req = entry.get("request") or {}
        url = (req.get("url") or "").strip()
        if "indiabix.com/logical-reasoning/" not in url:
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


def _sub_category_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/")
        parts = path.split("/")
        if "logical-reasoning" in parts:
            i = parts.index("logical-reasoning")
            if i + 1 < len(parts):
                return parts[i + 1]
        return "questions-and-answers"
    except Exception:
        return "questions-and-answers"


def _parse_answer_div(div) -> tuple[int, str]:
    """Return (correct_answer_idx, explanation). Default (0, '')."""
    if not div:
        return 0, ""
    text = div.get_text(separator=" ", strip=True)
    idx = 0
    m = ANSWER_OPTION_RE.search(text)
    if m:
        idx = OPTION_LETTER_TO_IDX.get(m.group(1).upper(), 0)
    expl = ""
    em = EXPLANATION_RE.search(text)
    if em:
        expl = em.group(1).strip()
    return idx, expl


def extract_questions_from_html(html: str, url: str) -> list[dict]:
    """Parse HTML and return list of question row dicts (id, category, sub_category, text, options, correct_answer_idx, explanation)."""
    soup = BeautifulSoup(html, "html.parser")
    sub_category = _sub_category_from_url(url)
    rows = []

    # Question text cells: .bix-td-qtxt
    q_cells = soup.select(".bix-td-qtxt")
    if not q_cells:
        # Fallback: look for table rows that contain question-like content
        q_cells = soup.select("td.bix-td-qtxt")

    for i, q_cell in enumerate(q_cells):
        q_text = q_cell.get_text(separator=" ", strip=True)
        if not q_text or len(q_text) < 10:
            continue

        # Options: often in following sibling row or next .bix-td-option / td with options
        options = []
        parent = q_cell.parent
        if parent:
            # Next row often has options (e.g. option table cells)
            next_row = parent.find_next_sibling("tr")
            if next_row:
                opt_cells = next_row.select("td.pq-padding-right, .bix-td-option, td[class*='option']")
                if not opt_cells:
                    opt_cells = next_row.find_all("td")
                for td in opt_cells[:4]:
                    t = td.get_text(separator=" ", strip=True)
                    if t and not t.startswith("View Answer"):
                        options.append(t)
        if not options:
            # Try next few siblings for any td with short text (option-like)
            current = parent
            for _ in range(5):
                current = current.find_next_sibling() if current else None
                if not current:
                    break
                for td in current.select("td"):
                    t = td.get_text(separator=" ", strip=True)
                    if 5 < len(t) < 500 and "View Answer" not in t and "Explanation" not in t:
                        options.append(t)
                        if len(options) >= 4:
                            break
                if len(options) >= 4:
                    break
        if len(options) < 2:
            continue
        # Normalize to 4 options (pad if needed)
        while len(options) < 4:
            options.append("")

        # View Answer link: href="#divAnswer_XXX" or aria-controls="divAnswer_XXX"
        answer_div = None
        link = q_cell.find_parent("tr")
        if link:
            link = link.find("a", href=re.compile(r"#divAnswer_\d+"))
        if not link:
            link = soup.find("a", href=re.compile(r"#divAnswer_\d+"))
        if link:
            href = link.get("href") or link.get("aria-controls") or ""
            match = re.search(r"divAnswer_(\d+)", href)
            if match:
                div_id = "divAnswer_" + match.group(1)
                answer_div = soup.find(id=div_id)

        correct_idx, explanation = _parse_answer_div(answer_div)
        if correct_idx >= len(options):
            correct_idx = 0
        explanation = (explanation or "")[:50000]

        # Stable id for upsert
        seed = f"indiabix_lr_{sub_category}_{q_text[:200]}_{options[0][:50]}"
        uid = str(uuid5(NAMESPACE_DNS, seed))

        rows.append({
            "id": uid,
            "category": "gat",
            "sub_category": sub_category,
            "text": q_text,
            "options": options,
            "correct_answer_idx": correct_idx,
            "explanation": explanation,
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
    parser = argparse.ArgumentParser(description="Extract IndiaBix logical-reasoning MCQs from HAR and upsert to Supabase.")
    parser.add_argument("har", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent / "www.indiabix.com.har", help="Path to .har file")
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
            logger.info("Sample row: %s", list(rows[0].keys()))
        return

    if not rows:
        logger.warning("No questions to upsert.")
        return

    upsert_questions(rows, chunk_size=args.chunk_size)
    logger.info("Upserted %d questions.", len(rows))


if __name__ == "__main__":
    main()
