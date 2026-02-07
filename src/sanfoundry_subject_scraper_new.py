"""
Extract Sanfoundry subject/CS MCQs via Playwright (real browser).
Targets: Data Structures, Algorithms, OOPS, OS, Networking, SE, Compilers, OpenCV.
Maps to category='subject' with sub_category from URL pattern.
"""
import argparse
import base64
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Callable
from urllib.parse import urljoin
from uuid import uuid5, NAMESPACE_DNS

from bs4 import BeautifulSoup

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.db_manager import upsert_questions, upsert_questions_chunk_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.sanfoundry.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_DELAY = 2
MAX_RETRIES = 3
# Loop guards (prev/next can be buggy or circular)
MAX_PREV_STEPS = 50
MAX_NEXT_PAGES_PER_SECTION = 500
# Timeouts (ms); override via env SANFOUNDRY_PAGE_TIMEOUT_MS / SANFOUNDRY_SELECTOR_TIMEOUT_MS
PAGE_TIMEOUT_MS = int(__import__("os").environ.get("SANFOUNDRY_PAGE_TIMEOUT_MS", "90000"))
SELECTOR_TIMEOUT_MS = int(__import__("os").environ.get("SANFOUNDRY_SELECTOR_TIMEOUT_MS", "35000"))

# Subject URL patterns -> sub_category mapping
SUBJECT_PATTERNS = {
    "1000-data-structure-questions-answers": "data_structures",
    "1000-data-structures-algorithms-ii-questions-answers": "algorithms_ii",
    "1000-object-oriented-programming-oops-questions-answers": "oops",
    "operating-system-questions-answers": "operating_system",
    "computer-network-questions-answers": "networking",
    "software-engineering-questions-answers": "software_engineering",
    "1000-compilers-questions-answers": "compilers",
    "1000-computer-fundamentals-questions-answers": "computer_fundamentals",
    "1000-opencv-questions-answers": "ai_opencv",
}

ANSWER_RE = re.compile(r"Answer\s*:\s*([a-d])", re.I)
EXPLANATION_RE = re.compile(r"Explanation\s*:\s*(.+)", re.I | re.DOTALL)

# Skip content from here onwards (Recommended Articles, Related Posts, Important Links, etc.)
STOP_PHRASES = re.compile(
    r"Recommended Articles|Related Posts|Important Links|To practice all areas|Join Sanfoundry|"
    r"Next\s*-\s*Data|Telegram|WhatsApp|Check .* Books|Practice .* MCQs|"
    r"Sanfoundry Global Education|complete set of \d+.*Multiple Choice",
    re.I,
)


def _load_har(path: Path) -> dict:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return json.load(f)


def _get_html_from_content(content: dict) -> Optional[str]:
    text = content.get("text")
    if text is None:
        return None
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            return None
    return text if isinstance(text, str) else None


def _is_html_response(entry: dict) -> bool:
    resp = entry.get("response") or {}
    for h in resp.get("headers") or []:
        if (h.get("name") or "").lower() == "content-type":
            return "text/html" in (h.get("value") or "").lower()
    return False


def _subject_from_url(url: str) -> Optional[str]:
    """Return sub_category if URL matches a subject pattern, else None."""
    path = (url.split("sanfoundry.com")[-1].split("?")[0] or "").strip("/")
    for pattern, sub_category in SUBJECT_PATTERNS.items():
        if pattern in path:
            return sub_category
    return None


def _section_prefix(pattern: str) -> str:
    """Prefix for section links (e.g. 1000-data-structure-... -> data-structure-...)."""
    if pattern.startswith("1000-"):
        return pattern.replace("1000-", "", 1)
    return pattern


# Next/Prev: site uses "» Next - ..." or "Next" or "Next »" etc.
NEXT_LINK_RE = re.compile(r"»\s*Next|Next\s*[-–]\s*|Next\s*»|^\s*Next\s*$", re.I)
PREV_LINK_RE = re.compile(r"«\s*Prev|Prev\s*[-–]\s*|Prev\s*«|^\s*Prev(ious)?\s*$", re.I)
# Fallback: link text is mainly "next" or "prev" (for pagination)
NEXT_TEXT_RE = re.compile(r"^\s*next\s*$|^\s*next\s*»|»\s*next", re.I)
PREV_TEXT_RE = re.compile(r"^\s*prev(ious)?\s*$|«\s*prev|prev\s*«", re.I)
SKIP_LINK_RE = re.compile(
    r"recommended|related\s*posts?|telegram|whatsapp|join\s*sanfoundry|check\s+.*books?|"
    r"practice\s+.*mcqs?|important\s*links?|certification|contact|about|privacy|login|signup",
    re.I,
)


def _has_prev_link(soup: BeautifulSoup, prefix: str) -> bool:
    """Check if page has a 'Prev' link (if not, it's the first page of the section)."""
    return _find_prev_link(soup, prefix) is not None


def _url_path(url: str) -> str:
    """Return path part of URL (after domain), normalized (no query/fragment, stripped)."""
    return url.split("sanfoundry.com")[-1].split("?")[0].split("#")[0].strip("/")


def _section_slug(url: str) -> str:
    """Canonical section id for dedupe (last path segment, lowercase)."""
    path = _url_path(url)
    return (path.split("/")[-1] or path).lower()


def _same_section(url: str, section_start_url: str) -> bool:
    """
    Permissive matching: return True for any URL that belongs to the subject's domain.
    E.g., if scraping Data Structures, accept URLs containing data-structure-interview, 
    experienced, freshers, etc.
    """
    section_path = _url_path(section_start_url)
    path = _url_path(url)
    
    # Extract subject identifier from section_start_url
    # For "1000-data-structure-questions-answers" -> "data-structure"
    # For "data-structure-questions-answers-array" -> "data-structure"
    section_parts = section_path.split("/")
    section_base = section_parts[-1] if section_parts else section_path
    
    # Remove common prefixes/suffixes to get core subject name
    subject_keywords = []
    for part in section_base.split("-"):
        if part and part not in ["1000", "questions", "answers", "interview"]:
            subject_keywords.append(part)
    
    # Build flexible patterns: accept variations like data-structure-interview, 
    # data-structure-experienced, data-structure-freshers, etc.
    if len(subject_keywords) >= 2:
        # Use first 2-3 keywords as core identifier (e.g., "data-structure", "object-oriented")
        core_subject = "-".join(subject_keywords[:2])
    elif len(subject_keywords) == 1:
        core_subject = subject_keywords[0]
    else:
        # Fallback to original logic
        section_slug = section_path.split("/")[-1]
        return (
            path == section_path
            or path.startswith(section_path + "/")
            or path == section_slug
            or path.startswith(section_slug + "/")
            or path.startswith(section_slug + "-")
        )
    
    # Check if path contains the core subject identifier
    path_lower = path.lower()
    core_lower = core_subject.lower()
    
    return (
        path == section_path
        or path.startswith(section_path + "/")
        or core_lower in path_lower
        or any(keyword.lower() in path_lower for keyword in subject_keywords[:3])
    )


def _rel_contains(a_tag, value: str) -> bool:
    """True if tag has rel=value (rel can be list or space-separated string)."""
    rel = a_tag.get("rel") or []
    if isinstance(rel, str):
        rel = [x.strip() for x in rel.split()]
    return value.lower() in [str(r).lower() for r in rel]


def _normalize_href(href: str, base: str, index_url: str, current_page_url: Optional[str] = None) -> Optional[str]:
    """Resolve href to absolute URL; return None if not sanfoundry.
    When current_page_url is set, relative hrefs are resolved against it (for next/prev on section pages).
    """
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return None
    if not href.startswith("http"):
        if href.startswith("/") and not href.startswith("//"):
            href = base + href
        else:
            # Resolve relative to current page when on a section (so page/2/ works)
            base_for_relative = (current_page_url or index_url).rstrip("/") + "/"
            href = urljoin(base_for_relative, href)
    if "sanfoundry.com" not in href:
        return None
    return href.rstrip("/") + "/"


def _find_prev_link(soup: BeautifulSoup, prefix: str, current_page_url: Optional[str] = None) -> Optional[str]:
    """Find Prev page link: prefer rel=\"prev\", then text « Prev / Prev - ...
    current_page_url: when set, relative hrefs are resolved against this (section pages).
    """
    base = BASE_URL.rstrip("/")
    index_url = base + "/"

    def norm(h: str):
        return _normalize_href(h, base, index_url, current_page_url)

    # 1. Prefer rel="prev"
    for a in soup.find_all("a", href=True):
        if not _rel_contains(a, "prev"):
            continue
        href = (a.get("href") or "").strip()
        full = norm(href)
        if not full:
            continue
        path = full.split("sanfoundry.com")[-1].split("?")[0].split("#")[0].strip("/")
        if prefix not in path:
            continue
        return full

    # 2. Fallback: text « Prev / Prev - ...
    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "")
        if not PREV_LINK_RE.search(text) or SKIP_LINK_RE.search(text):
            continue
        href = (a.get("href") or "").strip()
        full = norm(href)
        if not full:
            continue
        path = full.split("sanfoundry.com")[-1].split("?")[0].split("#")[0].strip("/")
        if prefix not in path:
            continue
        return full
    return None


def _find_next_link(soup: BeautifulSoup, prefix: str, current_page_url: Optional[str] = None) -> Optional[str]:
    """Find Next page link: prefer rel=\"next\", then text Next - ... / Next ».
    current_page_url: when set, relative hrefs are resolved against this (section pages).
    """
    base = BASE_URL.rstrip("/")
    index_url = base + "/"

    def href_ok(href: str) -> Optional[str]:
        full = _normalize_href((href or "").strip(), base, index_url, current_page_url)
        if not full:
            return None
        path = full.split("sanfoundry.com")[-1].split("?")[0].split("#")[0].strip("/")
        if prefix not in path:
            return None
        return full

    # 1. Prefer rel="next"
    for a in soup.find_all("a", href=True):
        if not _rel_contains(a, "next"):
            continue
        full = href_ok((a.get("href") or "").strip())
        if full:
            return full

    # 2. Fallback: text Next - ... / Next » in nav or whole page
    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "")
        if SKIP_LINK_RE.search(text):
            continue
        full = href_ok((a.get("href") or "").strip())
        if not full:
            continue
        if NEXT_LINK_RE.search(text) or NEXT_TEXT_RE.search(text) or (len(text) <= 8 and "next" in text.lower()):
            return full
    return None


def _discover_section_urls(soup: BeautifulSoup, pattern: str, index_url: str) -> List[str]:
    """
    Extracts every link from the 'Table of Contents' tables on the homepage.
    Targets table.sf-2col-tbl or div.sf-section structure: table -> td -> li -> a
    """
    base = BASE_URL.rstrip("/")
    urls = []
    seen = set()
    
    # Normalize index_url for comparison
    index_url_normalized = index_url.rstrip("/") + "/"
    
    # 1. Look for the specific tables (sf-2col-tbl)
    tables = soup.find_all("table", class_="sf-2col-tbl")
    
    # 2. If no tables, look for the sf-section div
    if not tables:
        divs = soup.find_all("div", class_="sf-section")
        if divs:
            tables = divs
    
    # 3. Also check for tables/divs with partial class matches
    if not tables:
        tables = soup.find_all("table", class_=lambda c: c and "sf-2col" in " ".join(c) if isinstance(c, list) else "sf-2col" in str(c))
    if not tables:
        tables = soup.find_all("div", class_=lambda c: c and "sf-section" in " ".join(c) if isinstance(c, list) else "sf-section" in str(c))
    
    # If still no containers, search entire page for section links
    if not tables:
        tables = [soup]
    
    # Extract links from containers
    for container in tables:
        for a in container.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            
            # Resolve to absolute URL
            if not href.startswith("http"):
                if href.startswith("/") and not href.startswith("//"):
                    href = base + href
                else:
                    href = urljoin(index_url, href)
            
            # Normalize URL
            full = href.split("?")[0].split("#")[0].rstrip("/") + "/"
            
            # Filter: Must be Sanfoundry and NOT the index itself
            if "sanfoundry.com" not in full:
                continue
            
            if full == index_url_normalized:
                continue
            
            # Ensure it's a content page (usually has 'questions-answers' or 'interview-questions' in slug)
            path = full.split("sanfoundry.com")[-1].strip("/")
            if "questions-answers" not in path.lower() and "interview-questions" not in path.lower():
                continue
            
            # Skip nav/social links by text
            link_text = (a.get_text(strip=True) or "").lower()
            if SKIP_LINK_RE.search(link_text):
                continue
            
            if full not in seen:
                seen.add(full)
                urls.append(full)
    
    logger.info(f"Successfully discovered {len(urls)} section links from the homepage.")
    return urls


class SanfoundrySubjectScraper:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats = {"total": 0, "valid": 0, "skipped": 0, "errors": 0}

    def _fetch_page_playwright(self, url: str, page) -> Optional[BeautifulSoup]:
        """Fetch page using Playwright. Uses domcontentloaded to avoid hanging on slow assets."""
        for attempt in range(MAX_RETRIES):
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                if resp and resp.status >= 400:
                    logger.warning(f"Fetch failed HTTP {resp.status} (attempt {attempt + 1}/{MAX_RETRIES})")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(2 + attempt)
                    continue
                try:
                    page.wait_for_selector("div.entry-content", timeout=SELECTOR_TIMEOUT_MS)
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                html = page.content()
                return BeautifulSoup(html, "html.parser")
            except Exception as e:
                logger.warning(f"Fetch failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 + attempt)
        return None
    
    def _parse_answer_and_explanation(self, collapse_div) -> Tuple[int, str]:
        """
        Parse correct answer and explanation from .collapseanswer div.
        Returns: (correct_answer_idx: 0-3, explanation: str)
        """
        if not collapse_div:
            return -1, ""
        
        text = collapse_div.get_text(separator=" ", strip=True)
        
        # Extract answer (a-d -> 0-3)
        idx = -1
        answer_match = ANSWER_RE.search(text)
        if answer_match:
            letter = answer_match.group(1).lower()
            idx = ord(letter) - ord('a')
        
        # Extract explanation (text after "Explanation:")
        explanation = ""
        expl_match = EXPLANATION_RE.search(text)
        if expl_match:
            explanation = expl_match.group(1).strip()
        
        return idx, explanation[:2000]
    
    def _clean_html_content(self, element):
        """Remove advertisement divs, 'Apply Now' spans, and other noise from question text."""
        if not element:
            return
        
        # Collect all tags first to avoid modifying tree during iteration
        tags_to_check = list(element.find_all(["div", "span", "p", "a"]))
        
        # Remove common ad/annoyance patterns
        for tag in tags_to_check:
            if tag is None:
                continue
            if not hasattr(tag, "attrs") or tag.attrs is None:
                continue
            try:
                classes = tag.get("class") or []
                class_str = " ".join(classes).lower() if isinstance(classes, list) else str(classes).lower()
                text = (tag.get_text(strip=True) or "").lower()
                
                # Remove ads, apply now buttons, etc.
                if any(keyword in class_str for keyword in ["ad", "advertisement", "adsense", "sponsor", "promo"]):
                    tag.decompose()
                    continue
                if "apply now" in text or "click here" in text or "buy now" in text:
                    tag.decompose()
                    continue
                if tag.name == "a":
                    href = tag.get("href") or ""
                    if ("javascript:" in href.lower() or href == "#") and len(text) < 5:
                        # Likely a button/link, not content
                        tag.decompose()
                        continue
            except (AttributeError, TypeError):
                # Skip if tag is invalid or was already decomposed
                continue

    def _extract_questions_from_page(self, soup: BeautifulSoup, sub_category: str) -> List[Dict]:
        """
        Parse questions from Sanfoundry subject page using span.collapseomatic as anchor.
        The MCQ text usually sits in the preceding <p> or <div>.
        The answer/explanation text is often in the immediate next sibling div.
        """
        rows = []
        seen_ids = set()
        
        # Anchor to main content (entry-content or article body)
        entry = soup.find("div", class_="entry-content")
        if not entry:
            entry = soup.find("article") or soup.find("div", class_=re.compile(r"content|post-body", re.I))
        if not entry:
            logger.warning("No entry-content / article found")
            return rows

        # Clean HTML: remove advertisements and noise
        self._clean_html_content(entry)

        # Remove "Recommended Articles", "Related Posts", etc. and everything after
        first_bad = None
        for elem in entry.find_all(True):
            if elem.get_text(strip=True) and STOP_PHRASES.search(elem.get_text(strip=True)):
                first_bad = elem
                break
        if first_bad:
            p = first_bad
            while p.parent and p.parent != entry:
                p = p.parent
            to_remove = [p]
            for sib in p.next_siblings:
                if hasattr(sib, "decompose"):
                    to_remove.append(sib)
            for node in to_remove:
                node.decompose()
            p.decompose()

        # Find all span.collapseomatic elements (these mark the answer/explanation toggle)
        collapse_spans = entry.find_all("span", class_="collapseomatic")
        if not collapse_spans:
            # Fallback: look for any span with class containing "collapse"
            collapse_spans = entry.find_all("span", class_=lambda c: c and "collapse" in " ".join(c) if isinstance(c, list) else "collapse" in str(c))
        
        if not collapse_spans:
            # Fallback: find elements containing "Answer: X" (one block per answer)
            logger.info("No span.collapseomatic found, trying fallback method with collapseanswer divs")
            collapse_divs = entry.find_all(class_="collapseanswer")
            if not collapse_divs:
                # Last resort: find any div/p containing "Answer:"
                seen_blocks = set()
                collapse_divs = []
                for tag in entry.find_all(string=ANSWER_RE):
                    parent = tag.parent
                    while parent and parent != entry:
                        if parent.name in ("div", "p", "section", "td", "li"):
                            key = id(parent)
                            if key not in seen_blocks:
                                seen_blocks.add(key)
                                collapse_divs.append(parent)
                            break
                        parent = parent.parent
                    if len(collapse_divs) > 500:
                        break
            
            if not collapse_divs:
                logger.info("No answer blocks found")
                return rows
            
            # Process fallback method with collapse_divs
            logger.info(f"Found {len(collapse_divs)} answer blocks (fallback method)")
            for collapse_idx, collapse_div in enumerate(collapse_divs):
                correct_idx, explanation = self._parse_answer_and_explanation(collapse_div)
                if correct_idx < 0:
                    logger.debug(f"Q{collapse_idx + 1}: Missing answer, skipping")
                    self.stats["skipped"] += 1
                    continue
                
                if not explanation:
                    explanation = ""
                
                # Find preceding question block (walk backwards from collapse_div)
                q_text = ""
                options = []
                prev_elem = collapse_div.find_previous_sibling()
                collected_blocks = []
                
                # Collect preceding siblings (up to 30 elements back)
                for _ in range(30):
                    if not prev_elem:
                        break
                    block_text = prev_elem.get_text(separator="\n", strip=True)
                    if block_text:
                        collected_blocks.append(block_text)
                    prev_elem = prev_elem.find_previous_sibling()
                
                # Reverse to process in order
                collected_blocks.reverse()
                
                # Parse question and options from collected blocks
                for block in collected_blocks:
                    lines = block.split("\n")
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        if re.match(r"^\d+\.\s+", line):
                            if not q_text:
                                q_text = re.sub(r"^\d+\.\s+", "", line).strip()
                            else:
                                break
                        elif re.match(r"^[a-d][\.\)\s]", line, re.I) and "Answer" not in line and "Explanation" not in line:
                            opt_clean = re.sub(r"^[a-d][\.\)\s]\s*", "", line, flags=re.I).strip()
                            if opt_clean and len(opt_clean) > 1:
                                options.append(opt_clean)
                                if len(options) >= 4:
                                    break
                    if q_text and len(options) >= 2:
                        break
                
                # Validation
                if not q_text or len(q_text) < 10:
                    logger.debug(f"Q{collapse_idx + 1}: Invalid question text, skipping")
                    self.stats["skipped"] += 1
                    continue
                
                if len(options) < 2:
                    logger.debug(f"Q{collapse_idx + 1}: Insufficient options ({len(options)}), skipping")
                    self.stats["skipped"] += 1
                    continue
                
                # Pad to 4 options
                while len(options) < 4:
                    options.append("")
                
                if correct_idx >= len(options):
                    correct_idx = 0
                
                # Create stable ID
                seed = f"sanfoundry_subject_{q_text[:150]}"
                row_id = str(uuid5(NAMESPACE_DNS, seed))
                
                if row_id in seen_ids:
                    logger.debug(f"Q{collapse_idx + 1}: Duplicate, skipping")
                    self.stats["skipped"] += 1
                    continue
                
                seen_ids.add(row_id)
                
                row = {
                    "id": row_id,
                    "category": "subject",
                    "sub_category": sub_category,
                    "text": q_text,
                    "options": options[:4],
                    "correct_answer_idx": correct_idx,
                    "explanation": explanation,
                    "source": "sanfoundry",
                }
                
                rows.append(row)
                logger.debug(f"Q{collapse_idx + 1}: Extracted '{q_text[:60]}...'")
            
            return rows
        
        logger.info(f"Found {len(collapse_spans)} span.collapseomatic elements")

        # Process each collapseomatic span
        for collapse_idx, span in enumerate(collapse_spans):
            # 1. Get the Question + Options (usually the paragraph immediately preceding the span)
            q_block = span.find_previous("p")
            if not q_block:
                # Try div or li as fallback
                q_block = span.find_previous(["div", "li"])
            
            if not q_block:
                logger.debug(f"Q{collapse_idx + 1}: No preceding question block found, skipping")
                self.stats["skipped"] += 1
                continue
            
            # Extract full text from question block
            full_text = q_block.get_text(separator="\n", strip=True)
            if not full_text or len(full_text) < 10:
                logger.debug(f"Q{collapse_idx + 1}: Empty or too short question block, skipping")
                self.stats["skipped"] += 1
                continue
            
            # Parse question text and options
            q_text = ""
            options = []
            lines = full_text.split("\n")
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Numbered question (1. Question text)
                if re.match(r"^\d+\.\s+", line):
                    if not q_text:
                        q_text = re.sub(r"^\d+\.\s+", "", line).strip()
                    else:
                        # Stop at next question
                        break
                
                # Option (a) or a. or A.)
                elif re.match(r"^[a-d][\.\)\s]", line, re.I) and "Answer" not in line and "Explanation" not in line:
                    opt_clean = re.sub(r"^[a-d][\.\)\s]\s*", "", line, flags=re.I).strip()
                    if opt_clean and len(opt_clean) > 1:
                        options.append(opt_clean)
                        if len(options) >= 4:
                            break
            
            # If we didn't find question in the block, try getting text directly
            if not q_text:
                # Sometimes question is in the same element, just extract all text
                q_text = full_text.split("\n")[0].strip()
                # Remove number prefix if present
                q_text = re.sub(r"^\d+\.\s+", "", q_text).strip()
            
            # 2. Get the Answer (found inside the div that follows the span)
            # The div usually has an ID like 'target-idXXXX'
            target_id = span.get("id")
            if isinstance(target_id, list):
                target_id = target_id[0] if target_id else None
            
            answer_div = None
            if target_id:
                # Try div with id="target-{target_id}" or id="{target_id}"
                answer_div = entry.find("div", id=f"target-{target_id}") or entry.find("div", id=target_id)
            
            # If not found by ID, look for next sibling div
            if not answer_div:
                next_sibling = span.find_next_sibling("div")
                if next_sibling:
                    answer_div = next_sibling
            
            # Fallback: find any div after this span that contains "Answer:"
            if not answer_div:
                for sibling in span.next_siblings:
                    if hasattr(sibling, "name") and sibling.name == "div":
                        if ANSWER_RE.search(sibling.get_text()):
                            answer_div = sibling
                            break
            
            # Parse answer and explanation
            correct_idx, explanation = self._parse_answer_and_explanation(answer_div) if answer_div else (-1, "")
            
            if correct_idx < 0:
                logger.debug(f"Q{collapse_idx + 1}: Missing answer, skipping")
                self.stats["skipped"] += 1
                continue
            
            if not explanation:
                explanation = ""
            
            # Clean question text (remove any remaining HTML artifacts)
            if q_text:
                q_text = re.sub(r"\s+", " ", q_text).strip()
            
            # Validation
            if not q_text or len(q_text) < 10:
                logger.debug(f"Q{collapse_idx + 1}: Invalid question text, skipping")
                self.stats["skipped"] += 1
                continue
            
            if len(options) < 2:
                logger.debug(f"Q{collapse_idx + 1}: Insufficient options ({len(options)}), skipping")
                self.stats["skipped"] += 1
                continue
            
            # Pad to 4 options
            while len(options) < 4:
                options.append("")
            
            if correct_idx >= len(options):
                correct_idx = 0
            
            # Create stable ID (question text hash for deduplication)
            seed = f"sanfoundry_subject_{q_text[:150]}"
            row_id = str(uuid5(NAMESPACE_DNS, seed))
            
            if row_id in seen_ids:
                logger.debug(f"Q{collapse_idx + 1}: Duplicate, skipping")
                self.stats["skipped"] += 1
                continue
            
            seen_ids.add(row_id)
            
            row = {
                "id": row_id,
                "category": "subject",
                "sub_category": sub_category,
                "text": q_text,
                "options": options[:4],
                "correct_answer_idx": correct_idx,
                "explanation": explanation,
                "source": "sanfoundry",
            }
            
            rows.append(row)
            logger.debug(f"Q{collapse_idx + 1}: Extracted '{q_text[:60]}...'")
        
        return rows

    def scrape_from_har(self, har_path: Path) -> List[Dict]:
        """Extract questions from HAR file (subject URLs only)."""
        har = _load_har(har_path)
        entries = har.get("log", {}).get("entries") or []
        all_rows = []
        seen_urls = set()
        for entry in entries:
            req = entry.get("request") or {}
            url = (req.get("url") or "").strip()
            sub_category = _subject_from_url(url)
            if not sub_category:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            resp = entry.get("response") or {}
            if resp.get("status") != 200:
                continue
            if not _is_html_response(entry):
                continue
            content = resp.get("content") or {}
            html = _get_html_from_content(content)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            rows = self._extract_questions_from_page(soup, sub_category)
            all_rows.extend(rows)
            logger.info(f"[HAR] {url} -> {sub_category}: {len(rows)} questions")
        return all_rows
    
    def _flush_chunk(
        self,
        pending: List[Dict],
        chunk_size: int,
        on_chunk: Optional[Callable[[List[Dict]], None]],
    ) -> List[Dict]:
        """If on_chunk is set and pending has >= chunk_size, flush one chunk and return remaining."""
        if not on_chunk or len(pending) < chunk_size:
            return pending
        chunk = pending[:chunk_size]
        remaining = pending[chunk_size:]
        try:
            on_chunk(chunk)
        except Exception as e:
            logger.warning("Chunk upsert failed (data not lost from scrape): %s", e)
        return remaining

    def scrape_all(
        self,
        subject_filter: Optional[set] = None,
        on_chunk: Optional[Callable[[List[Dict]], None]] = None,
        chunk_size: int = 200,
    ) -> List[Dict]:
        """Scrape all subject topics using Playwright (real browser bypasses 403).
        All rows have category='subject' and sub_category (e.g. data_structures, ai_opencv).

        Args:
            subject_filter: If provided, only scrape these subjects (e.g. {"data_structures"} or {"networking", "software_engineering"}).
            on_chunk: If set, call with each chunk of rows as soon as chunk_size is reached (minimizes data loss on crash/timeout).
            chunk_size: Size of each chunk when on_chunk is used.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        all_rows: List[Dict] = []
        pending: List[Dict] = []  # buffer for incremental upsert
        with sync_playwright() as p:
            # Prefer installed Chrome (same as when user opens link); fallback to Chromium
            try:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
            except Exception:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            context.set_default_timeout(PAGE_TIMEOUT_MS)
            page = context.new_page()
            try:
                for pattern, sub_category in SUBJECT_PATTERNS.items():
                    # Filter by subject if specified
                    if subject_filter and sub_category not in subject_filter:
                        continue
                    prefix = _section_prefix(pattern)
                    homepage_url = f"{BASE_URL}/{pattern}/"
                    
                    # Step 1: Visit homepage and discover all section links
                    logger.info(f"\n{'='*60}")
                    logger.info(f"SUBJECT: {sub_category.upper()}")
                    logger.info(f"Homepage: {homepage_url}")
                    logger.info(f"{'='*60}")
                    homepage_soup = self._fetch_page_playwright(homepage_url, page)
                    if not homepage_soup:
                        logger.warning(f"[{sub_category}] Failed to fetch homepage: {homepage_url}")
                        continue
                    time.sleep(REQUEST_DELAY)
                    
                    # Wait for section links to be in DOM (they may load after entry-content)
                    try:
                        page.wait_for_selector(f'a[href*="{prefix}"]', timeout=8000)
                    except Exception:
                        pass
                    homepage_soup = BeautifulSoup(page.content(), "html.parser")
                    
                    # Extract section links from homepage FIRST (before modifying soup with question extraction)
                    raw_sections = _discover_section_urls(homepage_soup, pattern, homepage_url)
                    
                    # Goal: extract questions from every page. Start with homepage.
                    homepage_rows = self._extract_questions_from_page(homepage_soup, sub_category)
                    if homepage_rows:
                        all_rows.extend(homepage_rows)
                        pending.extend(homepage_rows)
                        self.stats["total"] += len(homepage_rows)
                        self.stats["valid"] += len(homepage_rows)
                        logger.info(f"[{sub_category}] Homepage -> {len(homepage_rows)} questions")
                        while len(pending) >= chunk_size:
                            pending = self._flush_chunk(pending, chunk_size, on_chunk)
                    section_urls = [
                        u for u in raw_sections
                        if u.rstrip("/") != homepage_url.rstrip("/")
                    ]
                    
                    # Dedupe by section slug
                    seen_slugs = set()
                    deduped = []
                    for u in section_urls:
                        slug = _section_slug(u)
                        if slug and slug not in seen_slugs:
                            seen_slugs.add(slug)
                            deduped.append(u)
                    section_urls = deduped
                    
                    if not section_urls:
                        logger.warning(f"[{sub_category}] No sections found on homepage")
                        # Continue to next subject - homepage might have questions but no sections to traverse
                        continue
                    else:
                        logger.info(f"[{sub_category}] Found {len(section_urls)} section(s) to process")
                    
                    visited_global = set()  # Track absolute URLs across all sections
                    total_pages = 0
                    subject_question_count = 0
                    
                    # Process each discovered section link
                    for section_start_url in section_urls:
                        slug = _section_slug(section_start_url)
                        section_visited = set()
                        
                        # Normalize section_start_url to absolute URL
                        section_start_url_normalized = section_start_url.rstrip("/")
                        if section_start_url_normalized not in visited_global:
                            visited_global.add(section_start_url_normalized)
                        
                        # Skip if this is the homepage (homepage doesn't have prev/next navigation)
                        if section_start_url.rstrip("/") == homepage_url.rstrip("/"):
                            logger.info(f"[{sub_category}] Skipping homepage traversal (already processed)")
                            continue
                        
                        # ---------- Phase 1: Seek Start - crawl backward using rel="prev" until no more prev links exist ----------
                        first_page_url = section_start_url
                        logger.info(f"[{sub_category}] Section [{slug}]: landing at {first_page_url}")
                        soup = self._fetch_page_playwright(first_page_url, page)
                        if not soup:
                            logger.warning(f"[{sub_category}] Fetch failed: {first_page_url}")
                            continue
                        time.sleep(REQUEST_DELAY)
                        
                        prev_steps = 0
                        while prev_steps < MAX_PREV_STEPS:
                            # Use rel="prev" link (resolve relative hrefs against current page)
                            prev_url = _find_prev_link(soup, prefix, current_page_url=first_page_url)
                            if not prev_url:
                                # No more prev links, we're at the start
                                break
                            
                            # Normalize to absolute URL for deduplication
                            prev_url_normalized = prev_url.rstrip("/")
                            
                            # Check for cycles
                            if prev_url_normalized == first_page_url.rstrip("/"):
                                logger.info(f"[{sub_category}] Prev points to current page, stopping backward crawl")
                                break
                            
                            # Check if URL belongs to same subject section
                            if not _same_section(prev_url, section_start_url):
                                logger.info(f"[{sub_category}] Prev points to different section, stopping backward crawl")
                                break
                            
                            # Check for visited URLs (prevent infinite loops)
                            if prev_url_normalized in visited_global or prev_url_normalized in section_visited:
                                logger.warning(f"[{sub_category}] Prev would repeat visited page, stopping backward crawl")
                                break
                            
                            prev_steps += 1
                            logger.info(f"[{sub_category}] Prev (step {prev_steps}): {prev_url}")
                            
                            # Mark as visited before fetching
                            visited_global.add(prev_url_normalized)
                            section_visited.add(prev_url_normalized)
                            
                            first_page_url = prev_url
                            soup = self._fetch_page_playwright(first_page_url, page)
                            if not soup:
                                logger.warning(f"[{sub_category}] Fetch failed: {first_page_url}")
                                break
                            time.sleep(REQUEST_DELAY)
                        
                        if not soup:
                            continue
                        if prev_steps >= MAX_PREV_STEPS:
                            logger.warning(f"[{sub_category}] Prev loop limit reached for section [{slug}]")
                        
                        current_url = first_page_url
                        logger.info(f"[{sub_category}] First page of section [{slug}]: {current_url}")
                        
                        # ---------- Phase 2: Scrape Forward - extract questions and follow rel="next" until end ----------
                        next_pages = 0
                        while current_url and next_pages < MAX_NEXT_PAGES_PER_SECTION:
                            current_url_normalized = current_url.rstrip("/")
                            
                            # Cycle check: if we already scraped this URL in this section, stop
                            if current_url_normalized in section_visited:
                                logger.warning(f"[{sub_category}] Cycle detected at {current_url}, stopping section")
                                break
                            
                            # Mark as visited (before scrape so cycle check works on next iteration)
                            visited_global.add(current_url_normalized)
                            section_visited.add(current_url_normalized)
                            total_pages += 1
                            next_pages += 1
                            
                            logger.info(f"[{sub_category}] Page {total_pages} (section [{slug}]): {current_url}")
                            
                            # Fetch this page if we don't already have it (we have soup from Phase 1 for first page)
                            if total_pages > 1:
                                soup = self._fetch_page_playwright(current_url, page)
                                if not soup:
                                    logger.warning(f"[{sub_category}] Fetch failed: {current_url}")
                                    break
                                time.sleep(REQUEST_DELAY)
                            
                            # Extract questions from this page
                            rows = self._extract_questions_from_page(soup, sub_category)
                            all_rows.extend(rows)
                            pending.extend(rows)
                            self.stats["total"] += len(rows)
                            self.stats["valid"] += len(rows)
                            subject_question_count += len(rows)
                            if rows:
                                logger.info(f"[{sub_category}] {current_url} -> {len(rows)} questions")
                            while len(pending) >= chunk_size:
                                pending = self._flush_chunk(pending, chunk_size, on_chunk)
                            
                            # Find next link (resolve relative hrefs against current page)
                            next_url = _find_next_link(soup, prefix, current_page_url=current_url)
                            if not next_url:
                                logger.info(f"[{sub_category}] No Next link (rel=next or text), end of section [{slug}]")
                                break
                            
                            next_url_normalized = next_url.rstrip("/")
                            
                            # Check for cycles
                            if next_url_normalized in visited_global:
                                logger.warning(f"[{sub_category}] Next would repeat visited page, stopping section")
                                break
                            
                            # Check if URL belongs to same subject section
                            if not _same_section(next_url, section_start_url):
                                next_slug = _section_slug(next_url)
                                logger.info(f"[{sub_category}] Next link points to different section [{next_slug}], end of [{slug}]")
                                break
                            
                            current_url = next_url
                            logger.info(f"[{sub_category}] Next: {current_url}")
                        
                        if next_pages >= MAX_NEXT_PAGES_PER_SECTION:
                            logger.warning(f"[{sub_category}] Next page limit reached for section [{slug}]")
                    
                    logger.info(f"[{sub_category}] COMPLETE: {total_pages} page(s), {subject_question_count} questions")
            finally:
                context.close()
                browser.close()
        # Flush remaining chunk (incremental upsert)
        if on_chunk and pending:
            try:
                on_chunk(pending)
            except Exception as e:
                logger.warning("Final chunk upsert failed: %s", e)
        return all_rows


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Sanfoundry subject/CS MCQs (Data Structures, OOPS, OS, Networking, etc.)"
    )
    parser.add_argument("--har", type=Path, default=None, help="Extract from HAR file (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no upsert")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    parser.add_argument("--subject", type=str, default=None, help="Subject(s) to scrape: one name or comma-separated (e.g. 'data_structures' or 'networking,software_engineering')")
    args = parser.parse_args()

    scraper = SanfoundrySubjectScraper(dry_run=args.dry_run)
    # Incremental upsert: as soon as each chunk is full, upsert it (minimizes data loss on crash/timeout)
    on_chunk = None if args.dry_run else upsert_questions_chunk_client
    if args.har:
        if not args.har.exists():
            logger.error("HAR file not found: %s", args.har)
            sys.exit(1)
        logger.info("Extracting from HAR: %s", args.har)
        rows = scraper.scrape_from_har(args.har)
        if not args.dry_run and rows:
            upsert_questions(rows, chunk_size=args.chunk_size)
    else:
        # Parse --subject as single value or comma-separated list
        subject_filter = None
        if args.subject:
            subject_filter = {s.strip() for s in args.subject.split(",") if s.strip()}
        rows = scraper.scrape_all(
            subject_filter=subject_filter,
            on_chunk=on_chunk,
            chunk_size=args.chunk_size,
        )
    
    logger.info(f"\n=== Final Stats ===")
    logger.info(f"Total extracted: {scraper.stats['total']}")
    logger.info(f"Valid: {scraper.stats['valid']}")
    logger.info(f"Skipped (missing answer/explanation): {scraper.stats['skipped']}")
    logger.info(f"Errors: {scraper.stats['errors']}")
    
    if args.dry_run or not rows:
        if rows:
            logger.info(f"\nSample row:\n{rows[0]}")
        return
    
    if not args.har and on_chunk:
        logger.info("Subject questions upserted incrementally (chunks of %d)", args.chunk_size)
    elif rows:
        logger.info(f"Upserted {len(rows)} questions to Supabase")


if __name__ == "__main__":
    main()
