# Find More MCQs Online – Enrich Low-Count Sub-categories

Run `python test_db_counts.py --under 100` to see current shortfall. Below: **direct links** and **new sources** to scrape so you can enrich the DB.

## Gotest.com.pk (GAT – live scraper)

- **Source:** [gotest.com.pk](https://gotest.com.pk) – Verbal Intelligence and Quantitative Reasoning (all `category='gat'`, `source='gotest'`).
- **Run:** `python -m src.gotest_live_scraper` (optional: `--dry-run`, `--max-tests 4`, `--verbal-only`, `--quant-only`).
- **Indexes:** Verbal: https://gotest.com.pk/verbal-intelligence-test-online-prep/ ; Quantitative: https://gotest.com.pk/quantitative-reasoning-test-online/
- **Integration:** Included in `run_scrapers.bat`. Uses Playwright + BeautifulSoup; incremental upsert via `upsert_questions_chunk_client`.

---

## 1. Use existing sources more (no new site)

| Sub-category | Current | Source | How to get more |
|--------------|--------|--------|------------------|
| **number_series** | 74 | indiabix | IndiaBIX has Type 1–4 + many pages. Increase `max_questions` in `indiabix_scraper_v2.py` and ensure all slugs under `/logical-reasoning/` are scraped with full pagination. |
| **analogies** | 75 | indiabix | Same: scrape all analogy types and all pages. |
| **logical_problems** | 56 | indiabix | Crawl all logical-reasoning topic slugs; scrape every page. |
| **cause_and_effect** | 30 | indiabix | https://www.indiabix.com/logical-reasoning/cause-and-effect – scrape all pages. |
| **Verbal Analogies** | 18 | examveda | Examveda has multiple sections and pages: e.g. https://www.examveda.com/competitive-english/practice-mcq-question-on-verbal-analogies and https://www.examveda.com/competitive-reasoning/practice-mcq-question-on-analogy?section=6&page=2 – add scraper or HAR for `section` and `page` params. |
| **Completing Statements** | 33 | examveda | Check examveda competitive English section for this topic; scrape by section/page. |
| **Spelling Check** | 69 | examveda | Same – more sections/pages if available. |
| **Sentence Correction** | 98 | examveda | Same. |
| **ai_opencv** | 6 | sanfoundry | Run `python -m src.sanfoundry_subject_scraper_new --subject ai_opencv` and confirm all section links are followed; Sanfoundry has more OpenCV sets. |

---

## 2. New websites – GAT (logical / verbal / aptitude)

### GK Series (gkseries.com)
- **Number series (quantitative):**  
  https://www.gkseries.com/aptitude-questions/aptitude-questions-and-answers  
- **GK:**  
  https://www.gkseries.com/general-knowledge/gk-subjects  
- **Structure:** Topic listing → question pages with A–D options and “View Answer” / solutions.  
- **Action:** Record HAR for one number-series page, then write a scraper (e.g. `gkseries_scraper.py`) that maps topic → `sub_category`, outputs `category='gat'`, `source='gkseries'`.

### FresherGate (freshergate.com)
- **Number series:**  
  https://www.freshergate.com/logical-reasoning/number-series  
  Example set: https://www.freshergate.com/logical-reasoning/number-series/1784/10  
- **Letter series:**  
  https://www.freshergate.com/logical-reasoning/letter-series  
- **Logical reasoning (analogies, cause-effect, etc.):** Browse https://freshergate.com/ and logical-reasoning sub-pages.  
- **Action:** HAR + scraper; map to existing sub_categories (e.g. number_series, letter_and_symbol_series, cause_and_effect, analogies).

### GeeksforGeeks (geeksforgeeks.org) – Aptitude
- **Number series (solved):**  
  https://www.geeksforgeeks.org/aptitude/number-series-solved-questions-and-answers/  
  https://www.geeksforgeeks.org/aptitude/number-series-logical-reasoning-questions/  
- **Aptitude index:**  
  https://www.geeksforgeeks.org/aptitude/aptitude-questions-and-answers/  
- **Action:** Pages are article-style with one question + options + solution. Scraper can parse Q, A–D, correct answer, explanation; map to `number_series` or other GAT sub_category, `source='geeksforgeeks'`.

### Testbook (testbook.com)
- **Number series MCQs:**  
  https://testbook.com/objective-questions/mcq-on-number-series--5eea6a1039140f30f369e85f  
- **Cause and effect:**  
  https://testbook.com/objective-questions/mcq-on-cause-and-effect--5eea6a1539140f30f369f43e  
- **General / quantitative aptitude:**  
  https://testbook.com/aptitude-questions  
- **Action:** May require handling JS or login for full list; start with one topic (e.g. number series), HAR + scraper, `category='gat'`, appropriate `sub_category`, `source='testbook'`.

### TutorialsPoint (tutorialspoint.com)
- **Cause and effect test:**  
  https://www.tutorialspoint.com/reasoning/reasoning_cause_and_effect_online_test.htm  
- **Action:** Check structure; if MCQ + answers, add small scraper for cause_and_effect.

### Arthacs (arthacs.in)
- **Statement and assumptions:**  
  https://www.arthacs.in/logical-reasoning-statement-and-assumptions-explanation-and-multiple-choice-questions-with-answe  
- **Action:** Map to `statement_and_assumption`; one more source for logical reasoning.

---

## 3. Sub-categories and suggested source mapping

| Sub-category | Current count | Existing source | New sources to try |
|--------------|---------------|------------------|--------------------|
| number_series | 74 | indiabix | gkseries, freshergate, geeksforgeeks, testbook |
| analogies | 75 | indiabix | examveda (more pages), freshergate |
| Verbal Analogies | 18 | examveda | examveda (all sections/pages), indiabix |
| logical_problems | 56 | indiabix | indiabix (full crawl), freshergate |
| cause_and_effect | 30 | indiabix | testbook, tutorialspoint, freshergate |
| statement_and_assumption | 274 | indiabix | arthacs |
| letter_and_symbol_series | 12 | indiabix | freshergate (letter series) |
| theme_detection, matching_definitions, etc. | &lt;25 | indiabix | indiabix (all subsections + pages) |
| Completing Statements, Spelling, Sentence Correction | 33–98 | examveda | examveda (all sections/pages) |
| ai_opencv | 6 | sanfoundry | sanfoundry (full subject run) |
| coding_decoding | 9 | sanfoundry | geeksforgeeks, indiabix (if GAT) |

---

## 4. Next steps (in order)

1. **IndiaBIX** – In `src/indiabix_scraper_v2.py` (or HAR scraper), list all logical-reasoning slugs, remove or raise `max_questions`, and run full crawl for number_series, analogies, cause_and_effect, logical_problems, letter_and_symbol_series, theme_detection, etc. Re-run scraper and re-import.
2. **Examveda** – For Verbal Analogies, Completing Statements, Spelling, Sentence Correction: either export more JSONL (all sections/pages) or add a small live/HAR scraper that iterates over `section` and `page` and outputs same row format as importer.
3. **Sanfoundry** – Run subject scraper for `ai_opencv` only; confirm all section links and pagination are followed.
4. **Pick one new source** – e.g. **gkseries.com** (number series + aptitude) or **freshergate.com** (number series + letter series). Record a HAR for 1–2 pages, then add a scraper that:
   - Parses question text, options A–D, correct answer, explanation
   - Sets `category='gat'`, `sub_category` (e.g. number_series), `source='gkseries'` or `'freshergate'`
   - Upserts into `questions` (same schema as existing scrapers).

After each step, run `python test_db_counts.py --under 100` again to see updated counts.
