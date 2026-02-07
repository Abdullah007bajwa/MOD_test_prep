# Sub-categories with fewer than 100 MCQs

Run `python test_db_counts.py --under 100` to regenerate this list from the DB.

---

## Current shortfall (from last run)

| Count | Sub-category | Current source(s) |
|------:|--------------|-------------------|
| 1 | verbal_classification | indiabix |
| 3 | essential_part | indiabix |
| 6 | ai_opencv | sanfoundry |
| 9 | coding_decoding | sanfoundry |
| 9 | verbal_reasoning | indiabix |
| 10 | making_judgments | indiabix |
| 12 | letter_and_symbol_series | indiabix |
| 12 | logical_games | indiabix |
| 14 | matching_definitions | indiabix |
| 18 | Verbal Analogies | examveda |
| 18 | theme_detection | indiabix |
| 24 | artificial_language | indiabix |
| 30 | cause_and_effect | indiabix |
| 33 | Completing Statements | examveda |
| 36 | analyzing_arguments | indiabix |
| 56 | logical_problems | indiabix |
| 69 | Spelling Check | examveda |
| 74 | number_series | indiabix |
| 75 | analogies | indiabix |
| 98 | Sentence Correction | examveda |

---

## Do original sources have more?

### IndiaBIX (indiabix.com)
- **Number series:** Multiple types (Type 1–4), multiple pages per type → likely more than 74 if you scrape all types and pagination.
- **Analogies:** 6 types (instrument-function, whole-part, container-content, etc.) → likely more than 75 across types/pages.
- **Logical reasoning:** Many topics (logical_problems, cause_and_effect, statement_assumption, etc.) have multiple sections and pages. Scraper may have hit a limit or only one subsection.
- **Verbal / theme / matching / essential_part:** Same site; more content likely if you crawl all subsection URLs and pages.

**Action:** Review `indiabix_scraper_v2.py` / HAR scraper: increase `max_questions` or ensure all topic slugs and pagination are covered.

### Examveda (examveda.com)
- **Verbal Analogies:** Has practice MCQs and multiple sections (e.g. section=2 page=2). Your 18 may be one section only.
- **Completing Statements, Spelling Check, Sentence Correction:** Part of competitive English; likely more pages/sections if you scrape by section and page.
- **Action:** Check examveda JSONL or live site for these topic names; if import was from one file, see if more JSONL exports or URL sections exist for these topics.

### Sanfoundry
- **ai_opencv:** Only 6 in DB. Sanfoundry has “1000 OpenCV” and image-processing style sets; your scraper may have missed sets or only one subsection. Re-run subject scraper with `--subject ai_opencv` and confirm all section links are followed.
- **coding_decoding:** 9 in DB; may be under logical reasoning. Confirm if this is GAT (then source = indiabix/examveda) or subject (sanfoundry). If GAT, consider scraping from indiabix/examveda instead.

---

## New sources to try (by topic type)

| Topic type | New source | URL / notes |
|------------|------------|-------------|
| Number series, quantitative aptitude | GK Series | gkseries.com – aptitude questions, number series, with solutions |
| Number series, analogies, reasoning | FresherGate | freshergate.com – aptitude by category, free |
| Logical reasoning, verbal, number series | Learn Theta | learntheta.com – 1000s of aptitude MCQs, topic-wise |
| General aptitude practice | Practice Aptitude Tests | practiceaptitudetests.com – numerical/diagrammatic reasoning |
| GK / current affairs (already have pakmcqs) | GK Series | gkseries.com – GK MCQs by subject |

**Scraping:** Add HAR or live scrapers for one of these (e.g. gkseries or freshergate), map their topics to your `sub_category` and `category` (GAT), and ingest into the same `questions` table with a new `source` (e.g. `gkseries`, `freshergate`).

---

## Suggested next steps

1. **IndiaBIX:** Run scraper with higher limits and list all logical-reasoning topic slugs; ensure number_series, analogies, logical_problems, cause_and_effect, etc. are all scraped with pagination.
2. **Examveda:** If you have another export or URL list for Verbal Analogies, Completing Statements, Spelling, Sentence Correction, import those; otherwise add a small examveda scraper for these sections.
3. **Sanfoundry:** For ai_opencv, run `sanfoundry_subject_scraper_new.py --subject ai_opencv` and verify all section links and pages are crawled.
4. **New source:** Pick one (e.g. gkseries.com or freshergate.com), record a HAR or inspect HTML for number series / analogies, then add a scraper that outputs rows with `category='gat'` and appropriate `sub_category` and `source`.
