"""
MCQ Discovery Module for finding online MCQs for low-count subcategories.
Uses web search and source mapping to help users find more questions.
"""
import logging
from typing import List, Dict, Optional
from db import get_subcategory_counts

logger = logging.getLogger(__name__)

# Source mapping from SOURCES_TO_ENRICH_DB.md
KNOWN_SOURCES = {
    "number_series": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/number-series/", "notes": "Type 1-4, multiple pages"},
        {"name": "GK Series", "url": "https://www.gkseries.com/aptitude-questions/aptitude-questions-and-answers", "notes": "Aptitude questions"},
        {"name": "FresherGate", "url": "https://www.freshergate.com/logical-reasoning/number-series", "notes": "Number series practice"},
        {"name": "GeeksforGeeks", "url": "https://www.geeksforgeeks.org/aptitude/number-series-solved-questions-and-answers/", "notes": "Solved questions"},
        {"name": "Testbook", "url": "https://testbook.com/objective-questions/mcq-on-number-series--5eea6a1039140f30f369e85f", "notes": "MCQ practice"},
    ],
    "analogies": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/analogy/", "notes": "Multiple types"},
        {"name": "Examveda", "url": "https://www.examveda.com/competitive-reasoning/practice-mcq-question-on-analogy", "notes": "Multiple sections"},
        {"name": "FresherGate", "url": "https://www.freshergate.com/logical-reasoning/analogy", "notes": "Analogy practice"},
    ],
    "cause_and_effect": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/cause-and-effect/", "notes": "Multiple pages"},
        {"name": "Testbook", "url": "https://testbook.com/objective-questions/mcq-on-cause-and-effect--5eea6a1539140f30f369f43e", "notes": "MCQ practice"},
        {"name": "TutorialsPoint", "url": "https://www.tutorialspoint.com/reasoning/reasoning_cause_and_effect_online_test.htm", "notes": "Online test"},
        {"name": "FresherGate", "url": "https://www.freshergate.com/logical-reasoning/cause-and-effect", "notes": "Practice questions"},
    ],
    "letter_and_symbol_series": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/letter-series/", "notes": "Letter series"},
        {"name": "FresherGate", "url": "https://www.freshergate.com/logical-reasoning/letter-series", "notes": "Letter series practice"},
    ],
    "Verbal Analogies": [
        {"name": "Examveda", "url": "https://www.examveda.com/competitive-english/practice-mcq-question-on-verbal-analogies", "notes": "Multiple sections/pages"},
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/verbal-ability/analogy/", "notes": "Verbal analogies"},
    ],
    "coding_decoding": [
        {"name": "Sanfoundry", "url": "https://www.sanfoundry.com/logical-reasoning-questions-answers-coding-decoding/", "notes": "Logical reasoning"},
        {"name": "GeeksforGeeks", "url": "https://www.geeksforgeeks.org/reasoning-ability/coding-decoding/", "notes": "Coding decoding"},
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/coding-decoding/", "notes": "Practice questions"},
    ],
    "logical_problems": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/logical-problems/", "notes": "Full crawl needed"},
        {"name": "FresherGate", "url": "https://www.freshergate.com/logical-reasoning/logical-problems", "notes": "Practice sets"},
    ],
    "theme_detection": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/theme-detection/", "notes": "All subsections"},
    ],
    "matching_definitions": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/matching-definitions/", "notes": "All subsections"},
    ],
    "verbal_classification": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/verbal-ability/classification/", "notes": "Verbal classification"},
    ],
    "essential_part": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/essential-part/", "notes": "Essential part questions"},
    ],
    "making_judgments": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/making-judgments/", "notes": "Judgment questions"},
    ],
    "logical_games": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/logical-reasoning/logical-games/", "notes": "Logical games"},
    ],
    "verbal_reasoning": [
        {"name": "IndiaBIX", "url": "https://www.indiabix.com/verbal-ability/", "notes": "Verbal reasoning"},
    ],
    "ai_opencv": [
        {"name": "Sanfoundry", "url": "https://www.sanfoundry.com/1000-opencv-questions-answers/", "notes": "1000 OpenCV questions"},
    ],
}


def get_low_count_subcategories(threshold: int = 20, category: Optional[str] = None) -> Dict[str, int]:
    """
    Identify subcategories with fewer than threshold questions.
    
    Args:
        threshold: Minimum number of questions (default 20)
        category: Optional category filter (gat/subject)
    
    Returns:
        Dict mapping sub_category -> count for subcategories below threshold
    """
    try:
        all_counts = get_subcategory_counts(category)
        low_count = {sub: count for sub, count in all_counts.items() if count < threshold}
        return dict(sorted(low_count.items(), key=lambda x: x[1]))  # Sort by count ascending
    except Exception as e:
        logger.error(f"Error getting low-count subcategories: {e}")
        return {}


def get_sources_for_subcategory(sub_category: str) -> List[Dict]:
    """
    Get known online sources for a specific subcategory.
    
    Args:
        sub_category: The subcategory name
    
    Returns:
        List of source dicts with name, url, and notes
    """
    return KNOWN_SOURCES.get(sub_category, [])


def format_subcategory_name(sub_category: str) -> str:
    """Format subcategory name for display (replace underscores with spaces, title case)."""
    return sub_category.replace("_", " ").title()


def get_search_queries_for_subcategory(sub_category: str) -> List[str]:
    """
    Generate search queries for finding MCQs online for a subcategory.
    
    Args:
        sub_category: The subcategory name
    
    Returns:
        List of search query strings
    """
    formatted = format_subcategory_name(sub_category)
    queries = [
        f"{formatted} MCQs",
        f"{formatted} practice questions",
        f"{formatted} multiple choice questions",
        f"{formatted} aptitude questions",
    ]
    return queries
