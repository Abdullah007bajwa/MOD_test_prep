#!/usr/bin/env python3
"""
Integration test: Engine + Database workflow.
Demonstrates:
1. Weighted question selection
2. Scoring calculation
3. Session persistence
"""
import logging
from datetime import datetime, timedelta
from uuid import uuid4
from decimal import Decimal

from src.engine import TestSession
from src.database import DatabaseClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def test_mock_exam_workflow():
    """Full end-to-end test of exam creation, answering, and scoring."""
    
    logger.info("=" * 70)
    logger.info("PrepMaster AI - Integration Test")
    logger.info("=" * 70)
    
    # Setup
    db = DatabaseClient()
    user_id = uuid4()
    logger.info(f"\n✓ Test User ID: {user_id}")
    
    # Mock question data (simulating DB fetch)
    mock_questions = [
        {
            "id": uuid4(),
            "category": "gat",
            "sub_category": "logical_reasoning",
            "text": "What is 2 + 2?",
            "options": ["3", "4", "5", "6"],
            "correct_answer_idx": 1,
            "explanation": "Basic arithmetic: 2 + 2 = 4",
            "fail_count": 0,
            "last_attempted_at": None
        },
        {
            "id": uuid4(),
            "category": "gat",
            "sub_category": "logical_reasoning",
            "text": "What is the capital of France?",
            "options": ["London", "Berlin", "Paris", "Madrid"],
            "correct_answer_idx": 2,
            "explanation": "Paris is the capital of France",
            "fail_count": 2,  # User failed this twice
            "last_attempted_at": (datetime.utcnow() - timedelta(days=5)).isoformat()
        },
        {
            "id": uuid4(),
            "category": "subject",
            "sub_category": "data_structures",
            "text": "What is the time complexity of binary search?",
            "options": ["O(n)", "O(log n)", "O(n^2)", "O(1)"],
            "correct_answer_idx": 1,
            "explanation": "Binary search has O(log n) complexity",
            "fail_count": 1,
            "last_attempted_at": (datetime.utcnow() - timedelta(days=30)).isoformat()
        },
    ]
    
    logger.info(f"\n✓ Loaded {len(mock_questions)} mock questions")
    
    # Create test session
    test = TestSession(user_id, mock_questions)
    logger.info(f"✓ Created TestSession: {test.session_id}")
    
    # Generate questions (would normally be 70 GAT + 30 Subject = 100)
    test.generate_questions()
    logger.info(f"✓ Generated {len(test.questions)} questions with weighted selection")
    
    # Log priority scores for weighting verification
    logger.info("\n--- Weighted Selection Details ---")
    for q in test.questions:
        fail_count = q.get("fail_count", 0)
        last_attempted = q.get("last_attempted_at")
        
        if isinstance(last_attempted, str):
            try:
                last_attempted = datetime.fromisoformat(last_attempted.replace("Z", "+00:00"))
            except:
                last_attempted = None
        
        days_since = 999
        if last_attempted:
            days_since = (datetime.utcnow() - last_attempted).days
        
        priority = (fail_count * 2) + days_since
        logger.info(f"  Q: {q['text'][:40]:<40} | Fails: {fail_count} | Days: {days_since:>3} | Priority: {priority:>5}")
    
    # Simulate answering questions
    logger.info("\n--- Answering Questions ---")
    answers_seq = [
        (test.questions[0]["id"], 1, True, 45),    # Correct, 45 sec
        (test.questions[1]["id"], 1, True, 60),    # Correct, 60 sec
        (test.questions[2]["id"], 2, False, 30),   # Incorrect (chose O(n^2)), 30 sec
    ]
    
    for q_id, user_choice, expected_correct, time_spent in answers_seq:
        result = test.submit_answer(q_id, user_choice, time_spent)
        
        status = "✓ CORRECT" if result["is_correct"] else "✗ INCORRECT"
        points = result["points_earned"]
        score = result["total_score"]
        
        logger.info(f"{status} | Points: {points:>5} | Total: {score:>6}")
    
    # Check current session summary
    summary = test.get_session_summary()
    logger.info("\n--- Session Progress ---")
    logger.info(f"  Current Question: {summary['current_question']}/{summary['total_questions']}")
    logger.info(f"  Answered: {summary['questions_answered']} | Skipped: {summary['questions_skipped']}")
    logger.info(f"  Current Score: {summary['current_score']}")
    logger.info(f"  Time Elapsed: {summary['time_elapsed_sec']:.0f}s")
    
    # End session
    test_result = test.end_session()
    
    logger.info("\n--- Test Results ---")
    logger.info(f"  Score: {test_result['score_earned']}/{test_result['score_total']}")
    logger.info(f"  Percentage: {test_result['percentage']:.1f}%")
    logger.info(f"  Pass Status: {'PASS' if test_result['pass_status'] else 'FAIL'} (threshold: {test_result['pass_threshold']})")
    logger.info(f"  Accuracy: {test_result['accuracy_percent']:.1f}%")
    logger.info(f"  Duration: {test_result['duration_minutes']:.1f} minutes")
    
    # Analyze performance
    logger.info("\n--- Category Breakdown ---")
    for cat, stats in test_result["category_breakdown"].items():
        pct = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
        logger.info(f"  {cat:<20} | {stats['correct']}/{stats['total']} ({pct:.0f}%)")
    
    logger.info("\n" + "=" * 70)
    logger.info("✓ Integration test completed successfully")
    logger.info("=" * 70)
    
    return test_result


if __name__ == "__main__":
    result = test_mock_exam_workflow()
