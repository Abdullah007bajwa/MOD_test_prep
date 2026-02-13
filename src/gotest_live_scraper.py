"""
Live scraper for gotest.com.pk – Verbal Intelligence and Quantitative Reasoning (all GAT).
Uses Playwright + BeautifulSoup. No HAR parsing.

WatuPRO / GoTest behavior (why certain fixes are required):
- Paginator range shift: The footer does not show all 100+ question numbers at once; it shows
  blocks (e.g. 1–25). To reach question 26 you must click the "forward" gatekeeper (>>) first
  so the next block (26–50) appears; only then can we click "26".
- Race condition: After clicking an option or paginator, the DOM updates via an AJAX-like call.
  The script must wait (wait_for_timeout) for that update before reading the page, or it will
  see stale content and fail to find the answer/explanation.
- Forced interaction: GoTest hides the real <input> elements with CSS. Standard Playwright
  clicks fail because the element is "not visible". force=True clicks by coordinates and
  bypasses visibility checks.
"""
import argparse
import logging
import random
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from urllib.parse import urljoin
from uuid import uuid5, NAMESPACE_DNS

from bs4 import BeautifulSoup, Comment

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from src.db_manager import upsert_questions_chunk_client
except ImportError:
    upsert_questions_chunk_client = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Constants ---
VERBAL_INDEX_URL = "https://gotest.com.pk/verbal-intelligence-test-online-prep/"
QUANTITATIVE_INDEX_URL = "https://gotest.com.pk/quantitative-reasoning-test-online/"
BASE_URL = "https://gotest.com.pk"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_DELAY = 1.5
PAGE_TIMEOUT_MS = 60000
SELECTOR_TIMEOUT_MS = 25000
MAX_RETRIES = 3

# Test name (or slug) -> sub_category
GOTEST_NAME_TO_SUB_CATEGORY = {
    # Verbal
    "analogy verbal test": "analogies",
    "analogy verbal": "analogies",
    "non verbal analogy": "non_verbal_analogy",
    "non verbal analogy test": "non_verbal_analogy",
    "classification verbal test": "verbal_classification",
    "classification verbal": "verbal_classification",
    "non verbal classification": "non_verbal_classification",
    "coding-decoding verbal test": "coding_decoding",
    "coding and decoding": "coding_decoding",
    "coding and decoding test": "coding_decoding",
    "word formation": "word_formation",
    "prefixes": "prefixes",
    "suffixes": "suffixes",
    "jumbled spellings": "word_formation",
    "jumbled words": "word_formation",
    "sequence test": "sequence",
    "sequences test": "number_series",
    "commonsense test": "commonsense",
    "common sense": "commonsense",
    "comparison of ranking": "ranking",
    "blood relation": "blood_relation",
    "problem of age": "age_problems",
    "age problems": "age_problems",
    "questions on ages": "age_problems",
    "assigning mathematical signs": "assigning_mathematical_signs",
    "situation reaction": "situation_reaction",
    "non verbal intelligence test": "non_verbal_intelligence",
    "non verbal pattern": "non_verbal_pattern",
    "non verbal completion of series": "non_verbal_completion_series",
    # Quantitative
    "number of series": "number_series",
    "number of series test": "number_series",
    "letter series": "letter_and_symbol_series",
    "letter series test": "letter_and_symbol_series",
    "sequences and series": "number_series",
    "fractions and decimals": "fractions_decimals",
    "decimal fraction": "fractions_decimals",
    "fractions & decimals": "fractions_decimals",
    "percentages": "percentages",
    "percentage": "percentages",
    "ratio and proportion": "ratio_proportion",
    "ratio & proportion": "ratio_proportion",
    "averages": "averages",
    "average": "averages",
    "basic arithmetic": "basic_arithmetic",
    "arithmetic": "basic_arithmetic",
    "algebra": "algebra_equations",
    "equations (algebra)": "algebra_equations",
    "polynomials (algebra)": "algebra_polynomials",
    "inequalities (algebra)": "algebra_inequalities",
    "word problems (algebra)": "word_problems_algebra",
    "geometry": "geometry",
    "data interpretation": "data_interpretation",
    "simplification": "simplification",
    "h.c.f. & l.c.m.": "hcf_lcm",
    "numerical ability": "numerical_ability",
    "maths numerical": "numerical_ability",
    "profit loss": "profit_loss",
    "counting probability": "probability",
    "counting and probability": "probability",
    "square roots": "square_roots_cube_roots",
    "cube roots": "square_roots_cube_roots",
    "speed and work": "speed_and_work",
    "aptitude test": "aptitude_general",
    "quantitative reasoning": "quantitative_reasoning",
    "pattern recognition": "pattern_recognition",
    "analogies": "analogies",
}


def _discover_test_links(soup: BeautifulSoup, base_url: str, url_pattern: str) -> List[Tuple[str, str]]:
    """
    From a parsed index page, return list of (absolute_url, test_name) for gotest test pages.
    url_pattern: e.g. "gotest.com.pk/forces/" or "gotest.com.pk/aptitude-test/" to filter links.
    """
    base = base_url.rstrip("/") + "/"
    seen_urls = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        if not href.startswith("http"):
            href = urljoin(base, href)
        if url_pattern not in href or "gotest.com.pk" not in href:
            continue
        full = href.split("?")[0].split("#")[0].rstrip("/") + "/"
        if full in seen_urls:
            continue
        seen_urls.add(full)
        name = (a.get_text(strip=True) or "").strip()
        if not name or len(name) < 2:
            name = full.rstrip("/").split("/")[-2] or "unknown"
        out.append((full, name))
    return out


def _normalize_sub_category(test_name: str) -> str:
    """Map test name/link text to sub_category using dict + fallback slug."""
    lower = test_name.lower().strip()
    for key, sub in GOTEST_NAME_TO_SUB_CATEGORY.items():
        if key in lower:
            return sub
    # Fallback: slug from name (lowercase, replace spaces/special with underscore)
    slug = re.sub(r"[^\w\s-]", "", lower)
    slug = re.sub(r"[-\s]+", "_", slug).strip("_")
    return slug or "general"


def _get_page_soup(page, url: str) -> Optional[BeautifulSoup]:
    """Playwright goto + wait + return BeautifulSoup of page.content()."""
    for attempt in range(MAX_RETRIES):
        try:
            logger.info("  Fetching %s (attempt %s/%s)...", url[:60] + "..." if len(url) > 60 else url, attempt + 1, MAX_RETRIES)
            resp = page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            if resp and resp.status >= 400:
                logger.warning("Fetch failed HTTP %s (attempt %s/%s)", resp.status, attempt + 1, MAX_RETRIES)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 + attempt)
                continue
            try:
                page.wait_for_selector("#watupro_quiz, .watu-question, .entry-content, .post-content", timeout=SELECTOR_TIMEOUT_MS)
            except Exception:
                pass
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            html = page.content()
            return BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.warning("Fetch failed (attempt %s/%s): %s", attempt + 1, MAX_RETRIES, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 + attempt)
    return None


class GotestScraper:
    def __init__(self, dry_run: bool = False, max_tests: Optional[int] = None, max_questions_per_test: Optional[int] = None, allow_unknown_correct: bool = False, verbal_only: bool = False, quant_only: bool = False, single_url: Optional[str] = None):
        self.dry_run = dry_run
        self.max_tests = max_tests
        self.max_questions_per_test = max_questions_per_test
        self.allow_unknown_correct = allow_unknown_correct
        self.verbal_only = verbal_only
        self.quant_only = quant_only
        self.single_url = (single_url or "").strip().rstrip("/") + "/" if single_url else None
        self.stats = {"tests": 0, "questions": 0, "skipped": 0, "errors": 0}

    def _discover_all_test_urls(self, page) -> List[Tuple[str, str]]:
        """Load both index pages, discover test links, return (url, test_name). Order: quantitative first, then verbal (so --max-tests 1 = first quant test)."""
        quant_links = []
        verbal_links = []
        if not self.verbal_only:
            soup = _get_page_soup(page, QUANTITATIVE_INDEX_URL)
            if soup:
                links = _discover_test_links(soup, BASE_URL, "gotest.com.pk/aptitude-test/")
                quant_links = links
                logger.info("Quantitative index: %s test links", len(links))
            time.sleep(REQUEST_DELAY)
        if not self.quant_only:
            soup = _get_page_soup(page, VERBAL_INDEX_URL)
            if soup:
                links = _discover_test_links(soup, BASE_URL, "gotest.com.pk/forces/")
                verbal_links = links
                logger.info("Verbal index: %s test links", len(links))
            time.sleep(REQUEST_DELAY)
        # Quantitative first, then verbal; dedupe by URL (first occurrence wins)
        combined = []
        seen = set()
        for url, name in quant_links + verbal_links:
            u = url.split("?")[0].rstrip("/")
            if u not in seen:
                seen.add(u)
                combined.append((url, name))
        if self.max_tests and len(combined) > self.max_tests:
            combined = combined[: self.max_tests]
        return combined

    def _get_visible_question_indices(self, page) -> List[int]:
        """Return 0-based indices of question blocks currently visible. Same filter as Python: id question-N and has question-content/question-choices so count stays 50."""
        try:
            indices = page.evaluate("""() => {
                const sel = '.watu-question, .show-question, div[id^="questionDiv"]';
                const all = Array.from(document.querySelectorAll(sel));
                const real = all.filter(el => {
                    const id = (el.id || '').trim();
                    if (!/^question-\\d+$/.test(id)) return false;
                    return el.querySelector('.question-content, [class*="question-content"]') || el.querySelector('.question-choices, [class*="question-choices"]');
                });
                const nodes = real.length ? real : all;
                return Array.from(nodes)
                    .map((el, i) => ({ i, visible: el.offsetParent !== null && el.offsetHeight > 0 }))
                    .filter(x => x.visible)
                    .map(x => x.i);
            }""")
            return list(indices) if indices else []
        except Exception:
            return []

    def _get_first_visible_question_id(self, page) -> Optional[str]:
        """Return the DOM id of the first visible question block (for state-change verification)."""
        try:
            return page.evaluate("""() => {
                const sel = '.watu-question, .show-question, div[id^="questionDiv"]';
                const el = Array.from(document.querySelectorAll(sel))
                    .find(e => e.offsetParent !== null && e.offsetHeight > 0);
                return el ? (el.id || null) : null;
            }""")
        except Exception:
            return None

    def _click_question_block_link(self, page, next_question_num: int) -> bool:
        """
        Advance to the next block of questions (e.g. 26-50). GoTest WatuPRO pagination:

        - Paginator range: Footer shows blocks (e.g. 1-25). If target "26" is not visible,
          the script MUST find and click the >> (li.rewind-up) button so the next block appears.
        - After clicking a page number, wait_for_function verifies the first question ID on the
          page has changed. Do not return True until the DOM has swapped.
        - All clicks use force=True to bypass CSS that hides the real inputs.
        """
        if next_question_num < 2:
            return False
        target_num = str(next_question_num)
        old_first_id = self._get_first_visible_question_id(page)
        try:
            paginator = page.locator(".watupro-paginator-wrap, .watupro-paginator, [class*='paginator']").first
            paginator.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        try:
            btn = page.locator(".watupro-paginator-wrap, .watupro-paginator").first.get_by_role("listitem").get_by_text(target_num, exact=True).first
            try:
                visible = btn.is_visible()
            except Exception:
                visible = False
            if not visible:
                rewind = page.locator("li.rewind-up, [class*='rewind-up']").filter(has_text=">>").first
                try:
                    rewind.scroll_into_view_if_needed(timeout=3000)
                    rewind.click(force=True, timeout=5000)
                except Exception:
                    try:
                        page.evaluate("""() => {
                            const el = document.querySelector('li.rewind-up, [class*="rewind-up"]');
                            if (el && (el.textContent || '').includes('>>')) el.click();
                        }""")
                    except Exception:
                        pass
                page.wait_for_timeout(800)
                try:
                    visible = btn.is_visible()
                except Exception:
                    visible = False
            if not visible:
                clicked_target = page.evaluate("""(target) => {
                    const paginator = document.querySelector('.watupro-paginator-wrap, .watupro-paginator, [class*="paginator"]');
                    const root = paginator || document.body;
                    const links = root.querySelectorAll('a, button, span, li.page-link, li[onclick]');
                    for (const el of links) {
                        const t = (el.textContent || '').trim();
                        if (t === target) { el.click(); return true; }
                    }
                    if (typeof WatuPRO !== 'undefined' && WatuPRO.movePaginator) {
                        WatuPRO.movePaginator('up', parseInt(target, 10));
                        return true;
                    }
                    return false;
                }""", target_num)
                if not clicked_target:
                    return False
                page.wait_for_timeout(800)
                try:
                    visible = btn.is_visible()
                except Exception:
                    visible = False
            if visible:
                btn.scroll_into_view_if_needed(timeout=3000)
                btn.click(force=True, timeout=5000)
            else:
                clicked = page.evaluate("""(target) => {
                    const paginator = document.querySelector('.watupro-paginator-wrap, .watupro-paginator, [class*="paginator"]');
                    const root = paginator || document.body;
                    const links = root.querySelectorAll('a, button, span, li.page-link, li[onclick]');
                    for (const el of links) {
                        const t = (el.textContent || '').trim();
                        if (t === target) { el.click(); return true; }
                    }
                    if (typeof WatuPRO !== 'undefined' && WatuPRO.movePaginator) {
                        WatuPRO.movePaginator('up', parseInt(target, 10));
                        return true;
                    }
                    return false;
                }""", target_num)
                if not clicked:
                    return False
            page.wait_for_timeout(400)
            try:
                page.wait_for_function(
                    """(oldId) => {
                        const sel = '.watu-question, .show-question, div[id^="questionDiv"]';
                        const el = Array.from(document.querySelectorAll(sel))
                            .find(e => e.offsetParent !== null && e.offsetHeight > 0);
                        const currentId = el ? (el.id || '') : '';
                        return currentId !== '' && currentId !== oldId;
                    }""",
                    timeout=12000,
                    arg=old_first_id,
                )
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _extract_questions_from_test_page(self, page, url: str, sub_category: str) -> List[Dict]:
        """
        Load test URL once. Handle in-page (JS) pagination: only process visible question blocks,
        then click in-page paginator (or >> then page number) to show next block. _click_question_block_link
        does not return True until the first question ID on the page has changed (DOM swapped).
        """
        soup = _get_page_soup(page, url)
        if not soup:
            return []
        time.sleep(REQUEST_DELAY)
        all_rows = []
        view_num = 0
        seen_seeds = set()
        last_visible: Optional[tuple] = None
        questions_attempted_so_far = 0
        while view_num < 50:
            view_num += 1
            if self.max_questions_per_test is not None and questions_attempted_so_far >= self.max_questions_per_test:
                logger.info("  [View %s] Reached max_questions_per_test (%s), stopping.", view_num, self.max_questions_per_test)
                break
            visible = self._get_visible_question_indices(page)
            if not visible:
                logger.info("  [View %s] No visible question blocks, stopping.", view_num)
                break
            visible_key = tuple(sorted(visible))
            if last_visible is not None and visible_key == last_visible:
                logger.info("  [View %s] Same block as previous (indices %s...); paginator did not advance, stopping.", view_num, visible[:5] if len(visible) > 5 else visible)
                break
            last_visible = visible_key
            logger.info("  [View %s] %s visible question(s) (indices %s...).", view_num, len(visible), visible[:5] if len(visible) > 5 else visible)
            soup = BeautifulSoup(page.content(), "html.parser")
            rows, attempted = self._extract_questions_from_soup(
                page, soup, url, sub_category, visible_indices=set(visible), seen_seeds=seen_seeds, questions_attempted_so_far=questions_attempted_so_far
            )
            questions_attempted_so_far += attempted
            if rows:
                all_rows.extend(rows)
                logger.info("  [View %s] Extracted %s questions (total so far: %s).", view_num, len(rows), len(all_rows))
            next_q_num = max(visible) + 2
            if not self._click_question_block_link(page, next_q_num):
                logger.info("  No link for question %s (end of test).", next_q_num)
                break
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            time.sleep(0.4)
        return all_rows

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Detect Next / page link (URL-based); return next page URL or None. Not used for in-page JS pagination."""
        base = BASE_URL.rstrip("/") + "/"
        for a in soup.find_all("a", href=True):
            text = (a.get_text(strip=True) or "").lower()
            if "next" not in text and "page" not in text:
                continue
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            if not href.startswith("http"):
                href = urljoin(current_url, href)
            if "gotest.com.pk" not in href:
                continue
            full = href.split("#")[0].rstrip("/")
            if full != current_url.rstrip("/"):
                return full + "/"
        return None

    def _extract_questions_from_soup(
        self,
        page,
        soup: BeautifulSoup,
        test_url: str,
        sub_category: str,
        visible_indices: Optional[Set[int]] = None,
        seen_seeds: Optional[Set[str]] = None,
        questions_attempted_so_far: int = 0,
    ) -> List[Dict]:
        """Parse WatuPRO quiz: .watu-question or .show-question blocks; get options; resolve correct answer.
        If visible_indices is set, only process those block indices (for in-page pagination). If seen_seeds is set, skip rows already in it.
        If max_questions_per_test is set, only process that many questions per test (stops early so run doesn't hang)."""
        rows = []
        seen = seen_seeds if seen_seeds is not None else set()
        quiz = soup.find(id="watupro_quiz") or soup.find("form", class_=lambda c: c and "quiz" in " ".join(c) if isinstance(c, list) else "quiz" in str(c or ""))
        if not quiz:
            quiz = soup.find("div", class_="entry-content") or soup.find("div", class_="post-content") or soup
        question_blocks = quiz.find_all("div", class_=lambda c: c and ("watu-question" in " ".join(c) or "show-question" in " ".join(c)) if isinstance(c, list) else "watu-question" in str(c or "") or "show-question" in str(c or ""))
        if not question_blocks:
            question_blocks = quiz.find_all("div", id=re.compile(r"questionDiv|question_div", re.I))
        # Keep only blocks that are real questions (have content/choices) and have id question-N so we don't count injected feedback/explanation divs (fixes 50->68->83).
        question_blocks = [
            qb for qb in question_blocks
            if (qb.find(class_=lambda c: c and "question-content" in " ".join(c) if isinstance(c, list) else "question-content" in str(c or "")) or qb.find(class_=lambda c: c and "question-choices" in " ".join(c) if isinstance(c, list) else "question-choices" in str(c or "")))
            and (re.match(r"question-\d+$", (qb.get("id") or "").strip()))
        ]
        if not question_blocks:
            raw = quiz.find_all("div", class_=lambda c: c and ("watu-question" in " ".join(c) or "show-question" in " ".join(c)) if isinstance(c, list) else "watu-question" in str(c or "") or "show-question" in str(c or ""))
            question_blocks = [qb for qb in raw if qb.find(class_=lambda c: c and "question-content" in " ".join(c) if isinstance(c, list) else "question-content" in str(c or "")) or qb.find(class_=lambda c: c and "question-choices" in " ".join(c) if isinstance(c, list) else "question-choices" in str(c or ""))]
            if not question_blocks:
                question_blocks = quiz.find_all("div", id=re.compile(r"questionDiv|question_div", re.I))
        n_blocks = len(question_blocks)
        to_process = sorted(visible_indices) if visible_indices is not None else list(range(n_blocks))
        if self.max_questions_per_test is not None:
            remaining = max(0, self.max_questions_per_test - questions_attempted_so_far)
            to_process = to_process[:remaining]
            if not to_process:
                return rows, 0
        logger.info("  Parsing %s question block(s) (this view: %s)...", n_blocks, len(to_process))
        for q_idx in to_process:
            if q_idx >= n_blocks:
                continue
            qb = question_blocks[q_idx]
            logger.info("  Question %s/%s: extracting...", q_idx + 1, n_blocks)
            q_text_el = qb.find(class_=lambda c: c and "question-content" in " ".join(c) if isinstance(c, list) else "question-content" in str(c or ""))
            q_text = (q_text_el.get_text(separator=" ", strip=True) if q_text_el else "").strip() or (qb.get_text(separator=" ", strip=True)[:2000]).strip()
            if not q_text or len(q_text) < 5:
                continue
            seed = f"gotest_{sub_category}_{q_text[:200]}"
            if seed in seen:
                continue
            choices_el = qb.find(class_=lambda c: c and "question-choices" in " ".join(c) if isinstance(c, list) else "question-choices" in str(c or ""))
            if not choices_el:
                choices_el = qb
            choice_divs = choices_el.find_all(class_=lambda c: c and "watupro-question-choice" in " ".join(c) if isinstance(c, list) else "watupro-question-choice" in str(c or ""))
            options = []
            for ch in choice_divs[:10]:
                label = ch.find("label")
                t = (label.get_text(strip=True) if label else "").strip() or ch.get_text(strip=True)
                if t:
                    t = re.sub(r"^[A-Za-z][\.\)]\s*", "", t).strip()
                options.append(t or "")
            while len(options) < 2:
                options.append("")
            if len(options) < 2:
                self.stats["skipped"] += 1
                continue
            correct_idx = self._get_correct_answer_from_dom(qb, len(options))
            explanation = ""
            if correct_idx < 0 and page:
                logger.info("  Question %s/%s: correct not in DOM, clicking once to reveal answer + explanation...", q_idx + 1, n_blocks)
                correct_idx, explanation = self._get_correct_by_click(page, qb, choice_divs, len(options), q_idx + 1, n_blocks)
            if correct_idx < 0:
                if self.allow_unknown_correct:
                    correct_idx = 0
                    explanation = "(Correct answer not verified - gotest). " + (explanation or "")
                    logger.info("  Question %s/%s: saving with placeholder correct (index 0); fix manually if needed.", q_idx + 1, n_blocks)
                else:
                    self.stats["skipped"] += 1
                    continue
            row_id = str(uuid5(NAMESPACE_DNS, seed))
            n_opts = len(options)
            if correct_idx >= n_opts:
                correct_idx = n_opts - 1
            row = {
                "id": row_id,
                "category": "gat",
                "sub_category": sub_category,
                "text": q_text[:5000],
                "options": options[:10],
                "correct_answer_idx": correct_idx,
                "explanation": (explanation or "")[:2000],
                "source": "gotest",
            }
            rows.append(row)
            seen.add(seed)
            self.stats["questions"] += 1
            opt_letter = chr(ord("A") + correct_idx) if 0 <= correct_idx < 26 else str(correct_idx)
            logger.info("  Extracted Q%s: correct = option %s (index %s) | %s", q_idx + 1, opt_letter, correct_idx, (q_text[:55] + "…") if len(q_text) > 55 else q_text)
            if len(rows) % 5 == 0 or q_idx == to_process[-1]:
                logger.info("  Progress: %s/%s questions extracted.", len(rows), n_blocks)
        return rows, len(to_process)

    def _get_correct_answer_from_dom(self, qb, num_options: int) -> int:
        """Look for data-correct, input[type=radio][checked], or marker: .correct-answer, .watupro-screen-reader 'correct', or HTML comment with correct-answer."""
        for inp in qb.find_all("input", type="radio"):
            if inp.get("checked") or inp.get("data-correct"):
                name = inp.get("name") or ""
                val = inp.get("value") or ""
                idx = self._option_value_to_index(val, name, qb, num_options)
                if idx >= 0:
                    return idx
        for elem in qb.find_all(attrs={"data-correct": True}):
            val = elem.get("data-correct") or elem.get_text(strip=True)
            idx = self._option_value_to_index(str(val), "", qb, num_options)
            if idx >= 0:
                return idx
        choice_divs = qb.find_all(class_=lambda c: c and "watupro-question-choice" in " ".join(c) if isinstance(c, list) else "watupro-question-choice" in str(c or ""))
        choices = [ch for ch in choice_divs[:10] if ch.find("input", type="radio")][:num_options]
        if len(choices) < 2:
            choices = choice_divs[:num_options]
        for i, ch in enumerate(choices):
            if ch.find(class_=lambda c: c and ("correct-answer" in " ".join(c) or "correct_answer" in " ".join(c) or "right-answer" in " ".join(c)) if isinstance(c, list) else "correct-answer" in str(c or "") or "correct_answer" in str(c or "") or "right-answer" in str(c or "")):
                return i
            cls = " ".join(ch.get("class") or []).lower()
            if "correct-answer" in cls or "correct_answer" in cls or "right-answer" in cls:
                return i
            sr = ch.find(class_=re.compile(r"watupro-screen-reader", re.I))
            if sr and (sr.get_text(strip=True) or "").strip().lower() == "correct":
                return i
        for comment in qb.find_all(string=lambda s: isinstance(s, Comment) and ("correct-answer" in str(s).lower() or "correct_answer" in str(s).lower())):
            p = comment.parent
            for _ in range(10):
                if not p:
                    break
                if p.get("class") and "watupro-question-choice" in " ".join(p.get("class") or []):
                    for ii, ch in enumerate(choices):
                        if ch == p or (hasattr(p, "parents") and ch in list(p.parents)):
                            return ii
                    break
                p = getattr(p, "parent", None)
        return -1

    def _option_value_to_index(self, value: str, name: str, qb, num_options: int) -> int:
        """Map value/name to 0..N-1. WatuPRO often uses answer IDs; match by order of choices."""
        choice_divs = qb.find_all(class_=lambda c: c and "watupro-question-choice" in " ".join(c) if isinstance(c, list) else "watupro-question-choice" in str(c or ""))
        for i, ch in enumerate(choice_divs[:10]):
            inp = ch.find("input", type="radio")
            if inp and (inp.get("value") == value or inp.get("name") == name):
                return i
            if str(i) == value or value in (ch.get("id") or ""):
                return i
        letter = (value or "").strip().upper()
        if letter and ord("A") <= ord(letter) <= ord("Z"):
            return min(ord(letter) - ord("A"), num_options - 1)
        return -1

    def _get_correct_by_click(
        self, page, qb, choice_divs: list, num_options: int, q_num: int = 0, q_total: int = 0
    ) -> Tuple[int, str]:
        """
        Click one option (force=True, no visibility check) to reveal correct answer.
        Wait 1200ms for "Correct" marker to render, then parse by markers:
        .correct-answer, .watupro-screen-reader "correct", or HTML comment containing correct-answer.
        Fallback: click Explanation button and regex "Correct Answer: (X)".
        """
        correct_answer_re = re.compile(
            r"correct\s+answer\s*[:\s]+([a-j])|"
            r"right\s+answer\s*[:\s]+([a-j])|"
            r"answer\s*[:\s]+([a-j])\s*[\.\)]|"
            r"answer\s*[:\s]+([a-j])\s*$|"
            r"\(([a-j])\)\s*correct|"
            r"Correct Answer:\s*([A-J])",
            re.I,
        )
        try:
            first_inp = qb.find("input", type="radio")
            name = (first_inp.get("name") or "").strip() if first_inp else None
            if not name:
                return -1, ""
            qid = (qb.get("id") or "").strip()
            if qid:
                first_radio = page.query_selector(f'[id="{qid}"] input[type="radio"]')
            else:
                first_radio = None
            if not first_radio:
                radios = page.query_selector_all(f'input[type="radio"][name="{name}"]')
                first_radio = radios[0] if radios else None
            if not first_radio:
                return -1, ""
            if qid:
                try:
                    page.evaluate("""(id) => { const el = document.getElementById(id); if (el) el.scrollIntoView({ block: "center", behavior: "instant" }); }""", qid)
                    time.sleep(0.3)
                except Exception:
                    pass
            clicked = False
            try:
                first_radio.scroll_into_view_if_needed(timeout=5000)
                first_radio.click(force=True, timeout=5000)
                clicked = True
            except Exception:
                if qid:
                    try:
                        page.locator(f'[id="{qid}"] label').first.click(force=True, timeout=5000)
                        clicked = True
                    except Exception:
                        pass
                if not clicked and name:
                    try:
                        page.locator(f'input[type="radio"][name="{name}"]').first.locator("xpath=..").locator("label").first.click(force=True, timeout=5000)
                        clicked = True
                    except Exception:
                        pass
                if not clicked and qid:
                    try:
                        page.locator(f'[id="{qid}"] div.watupro-question-choice').first.click(force=True, timeout=5000)
                        clicked = True
                    except Exception:
                        pass
            if not clicked:
                return -1, ""
            try:
                page.evaluate("""() => {
                    const texts = ['Submit', 'Check', 'View Answer', 'Show Answer', 'Check Answer', 'Next'];
                    const el = Array.from(document.querySelectorAll('a, button, input[type="submit"], span, div[role="button"]'))
                        .find(e => { const t = (e.textContent || e.value || '').trim().toLowerCase(); return texts.some(x => t.includes(x.toLowerCase())); });
                    if (el) el.click();
                }""")
                page.wait_for_timeout(300)
            except Exception:
                pass
            if qid:
                try:
                    page.wait_for_selector(
                        f'[id="{qid}"] .correct-answer, [id="{qid}"] [class*="correct-answer"], [id="{qid}"] .watupro-screen-reader, [id="{qid}"] input[type="radio"]:checked',
                        timeout=2200,
                        state="attached",
                    )
                except Exception:
                    pass
            page.wait_for_timeout(400)
            try:
                page.evaluate("""() => {
                    const el = Array.from(document.querySelectorAll('a, button, span, div[role="button"]'))
                        .find(e => e.textContent && e.textContent.trim().toLowerCase().includes('explanation'));
                    if (el) el.click();
                }""")
                page.wait_for_timeout(250)
            except Exception:
                pass
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            scope = soup.find("div", id=qid) if qid else None
            if not scope and name:
                inp = soup.find("input", type="radio", attrs={"name": name})
                if inp:
                    p = inp.parent
                    for _ in range(15):
                        if not p:
                            break
                        if p.name == "div" and (p.get("id") or "").startswith("question"):
                            scope = p
                            break
                        if p.get("class") and ("watu-question" in " ".join(p.get("class") or []) or "show-question" in " ".join(p.get("class") or [])):
                            scope = p
                            break
                        p = getattr(p, "parent", None)
            if not scope:
                scope = soup
            all_choice_divs = scope.find_all(
                class_=lambda c: c and "watupro-question-choice" in " ".join(c)
                if isinstance(c, list)
                else "watupro-question-choice" in str(c or ""),
            )
            choices = [ch for ch in all_choice_divs[:10] if ch.find("input", type="radio")][:num_options]
            if len(choices) < 2:
                choices = all_choice_divs[:num_options]
            correct_idx = -1
            def _index_from_regex(text: str):
                out = -1
                for m in correct_answer_re.finditer(text):
                    letter = (m.group(1) or m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6) or "").upper()
                    if letter in "ABCDEFGHIJ":
                        out = min(ord(letter) - ord("A"), len(choices) - 1)
                return out
            for comment in scope.find_all(string=lambda s: isinstance(s, Comment) and "correct-answer" in str(s).lower()):
                p = comment.parent
                for _ in range(10):
                    if not p:
                        break
                    if p.get("class") and "watupro-question-choice" in " ".join(p.get("class") or []):
                        for ii, ch in enumerate(choices):
                            if ch == p or p in ch.descendants or (hasattr(p, "parents") and ch in list(p.parents)):
                                correct_idx = ii
                                break
                        break
                    p = getattr(p, "parent", None)
                if correct_idx >= 0:
                    break
            if correct_idx < 0:
                for i, ch in enumerate(choices):
                    cls = " ".join(ch.get("class") or []).lower()
                    if "correct-answer" in cls or "correct_answer" in cls or "right-answer" in cls or ("correct" in cls and "incorrect" not in cls):
                        correct_idx = i
                        break
                    if ch.find(class_=lambda c: c and ("correct-answer" in " ".join(c) or "correct_answer" in " ".join(c) or "right-answer" in " ".join(c)) if isinstance(c, list) else "correct-answer" in str(c or "") or "correct_answer" in str(c or "") or "right-answer" in str(c or "")):
                        correct_idx = i
                        break
                    sr = ch.find(class_=re.compile(r"watupro-screen-reader", re.I))
                    if sr and (sr.get_text(strip=True) or "").strip().lower() == "correct":
                        correct_idx = i
                        break
                    nxt = ch.find_next_sibling()
                    if nxt and hasattr(nxt, "find"):
                        sr2 = nxt.find(class_=re.compile(r"watupro-screen-reader", re.I))
                        if sr2 and (sr2.get_text(strip=True) or "").strip().lower() == "correct":
                            correct_idx = i
                            break
                    inp = ch.find("input", type="radio")
                    if inp and (inp.get("checked") or inp.get("data-correct")):
                        correct_idx = i
                        break
            if correct_idx < 0 and qid:
                for sr_el in soup.find_all(class_=re.compile(r"watupro-screen-reader", re.I)):
                    if (sr_el.get_text(strip=True) or "").strip().lower() != "correct":
                        continue
                    p = sr_el.parent
                    choice_div = None
                    for _ in range(15):
                        if not p:
                            break
                        if p.get("id") == qid:
                            break
                        if p.get("class") and "watupro-question-choice" in " ".join(p.get("class") or []):
                            choice_div = p
                        p = getattr(p, "parent", None)
                    if not choice_div:
                        continue
                    block = soup.find("div", id=qid)
                    if not block or (choice_div not in block.descendants and choice_div != block):
                        continue
                    real_in_scope = [c for c in block.find_all(class_=lambda c: c and "watupro-question-choice" in " ".join(c) if isinstance(c, list) else "watupro-question-choice" in str(c or "")) if c.find("input", type="radio")][:num_options]
                    for ii, c in enumerate(real_in_scope):
                        if c == choice_div or choice_div in c.descendants or (hasattr(choice_div, "parents") and c in list(choice_div.parents)):
                            correct_idx = ii
                            break
                    if correct_idx >= 0:
                        break
            if correct_idx < 0 and qid:
                try:
                    idx_from_page = page.evaluate("""(id, numOpts) => {
                        const root = document.getElementById(id);
                        if (!root) return -1;
                        const all = root.querySelectorAll('.watupro-question-choice, [class*="question-choice"]');
                        const choices = Array.from(all).filter(el => el.querySelector('input[type="radio"]')).slice(0, numOpts);
                        for (let i = 0; i < choices.length; i++) {
                            const el = choices[i];
                            if ((el.className || '').toLowerCase().includes('correct-answer')) return i;
                            if (el.querySelector('.correct-answer, [class*="correct-answer"]')) return i;
                            const sr = el.querySelector('.watupro-screen-reader');
                            if (sr && (sr.textContent || '').trim().toLowerCase() === 'correct') return i;
                            const next = el.nextElementSibling;
                            if (next && next.classList.contains('watupro-screen-reader') && (next.textContent || '').trim().toLowerCase() === 'correct') return i;
                            if ((el.textContent || '').includes('✓') || (el.textContent || '').includes('✔')) return i;
                        }
                        return -1;
                    }""", qid, num_options)
                    if isinstance(idx_from_page, int) and 0 <= idx_from_page < num_options:
                        correct_idx = idx_from_page
                except Exception:
                    pass
            feedback = soup.find(id="watuPracticeFeedback") or soup.find(class_=re.compile(r"watupro.*feedback|feedback|explanation", re.I))
            if correct_idx < 0:
                correct_idx = _index_from_regex((feedback.get_text(separator=" ", strip=True) if feedback else "")[:2000])
                if correct_idx >= 0:
                    logger.info("  Question %s/%s: found correct at option %s (from feedback regex).", q_num, q_total, correct_idx + 1)
            if correct_idx < 0:
                correct_idx = _index_from_regex(scope.get_text(separator=" ", strip=True)[:2000])
                if correct_idx >= 0:
                    logger.info("  Question %s/%s: found correct at option %s (from scope regex).", q_num, q_total, correct_idx + 1)
            if correct_idx < 0:
                main = soup.find("div", class_="entry-content") or soup.find(id="watupro_quiz") or soup.body or soup
                if main:
                    correct_idx = _index_from_regex(main.get_text(separator=" ", strip=True)[:3000])
                    if correct_idx >= 0:
                        logger.info("  Question %s/%s: found correct at option %s (from page regex).", q_num, q_total, correct_idx + 1)
            if correct_idx >= 0:
                logger.info("  Question %s/%s: found correct at option %s.", q_num, q_total, correct_idx + 1)
            explanation = ""
            expl_str = soup.find(string=re.compile(r"EXPLANATION\s*:", re.I))
            if expl_str:
                parent = expl_str.parent
                for _ in range(5):
                    if not parent:
                        break
                    if parent.name in ("div", "p", "section", "td"):
                        explanation = (parent.get_text(separator=" ", strip=True) or "")[:2000]
                        break
                    parent = getattr(parent, "parent", None)
            if not explanation and feedback:
                explanation = (feedback.get_text(separator=" ", strip=True) or "")[:2000]
            elif not explanation and scope:
                next_el = scope.find_next_sibling() or scope.find_next("div")
                if next_el and next_el.get("id") != qid:
                    explanation = (next_el.get_text(separator=" ", strip=True) or "")[:2000]
            return correct_idx, explanation
        except Exception as e:
            logger.warning("Click-to-reveal failed for question %s: %s", q_num, e)
        return -1, ""

    def run(
        self,
        on_chunk: Optional[callable] = None,
        chunk_size: int = 200,
    ) -> List[Dict]:
        """Playwright: discover test URLs, for each test extract questions; optional incremental upsert."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []
        all_rows = []
        pending = []
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
            except Exception:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            context.set_default_timeout(PAGE_TIMEOUT_MS)
            page = context.new_page()
            try:
                test_links = self._discover_all_test_urls(page)
                logger.info("Total test URLs to scrape: %s", len(test_links))
                total_tests = len(test_links)
                for idx, (test_url, test_name) in enumerate(test_links, 1):
                    self.stats["tests"] += 1
                    sub = _normalize_sub_category(test_name)
                    logger.info("Test [%s/%s]: %s -> sub_category=%s", idx, total_tests, test_url, sub)
                    logger.info("  Loading test page...")
                    try:
                        rows = self._extract_questions_from_test_page(page, test_url, sub)
                        all_rows.extend(rows)
                        pending.extend(rows)
                        logger.info("  Total from this test: %s", len(rows))
                        while on_chunk and len(pending) >= chunk_size:
                            chunk = pending[:chunk_size]
                            pending = pending[chunk_size:]
                            on_chunk(chunk)
                    except Exception as e:
                        logger.warning("Failed test %s: %s", test_url, e)
                        self.stats["errors"] += 1
                    time.sleep(REQUEST_DELAY)
            finally:
                context.close()
                browser.close()
        if on_chunk and pending:
            try:
                on_chunk(pending)
            except Exception as e:
                logger.warning("Final chunk upsert failed: %s", e)
        return all_rows


def main():
    parser = argparse.ArgumentParser(description="Scrape gotest.com.pk Verbal & Quantitative (GAT) MCQs")
    parser.add_argument("--dry-run", action="store_true", help="Discover and extract only, no upsert")
    parser.add_argument("--max-tests", type=int, default=None, help="Limit to N random tests (e.g. 4 for testing)")
    parser.add_argument("--max-questions", type=int, default=None, help="Max questions to attempt per test (avoids long hangs when click-to-reveal fails; e.g. 5 for quick test)")
    parser.add_argument("--allow-unknown-correct", action="store_true", help="Save questions even when correct answer not detected (use placeholder 0; fix manually or re-scrape later)")
    parser.add_argument("--verbal-only", action="store_true", help="Only verbal index")
    parser.add_argument("--quant-only", action="store_true", help="Only quantitative index")
    parser.add_argument("--url", type=str, default=None, help="Scrape only this test URL (e.g. pattern-recognition test)")
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size")
    args = parser.parse_args()

    scraper = GotestScraper(
        dry_run=args.dry_run,
        max_tests=args.max_tests,
        max_questions_per_test=args.max_questions,
        allow_unknown_correct=args.allow_unknown_correct,
        verbal_only=args.verbal_only,
        quant_only=args.quant_only,
        single_url=args.url,
    )
    on_chunk = None if args.dry_run else upsert_questions_chunk_client
    rows = scraper.run(on_chunk=on_chunk, chunk_size=args.chunk_size)

    logger.info("=== Final Stats ===")
    logger.info("Tests processed: %s", scraper.stats["tests"])
    logger.info("Questions extracted: %s", scraper.stats["questions"])
    logger.info("Skipped: %s", scraper.stats["skipped"])
    logger.info("Errors: %s", scraper.stats["errors"])

    if args.dry_run and rows:
        logger.info("Sample row: %s", rows[0])
    elif not args.dry_run and rows:
        logger.info("Upserted incrementally (source=gotest)")


if __name__ == "__main__":
    main()
