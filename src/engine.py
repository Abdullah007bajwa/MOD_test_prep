"""
Mock Test Engine: Weighted question selection, scoring, and session management.
Implements 70/30 GAT/Subject split with priority-based weighting (fail_count + days_since_practiced).
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from uuid import uuid4, UUID
import random
from decimal import Decimal

logger = logging.getLogger(__name__)


class TestSession:
    """Manages a single mock test session with weighted question selection and scoring."""
    
    # Scoring constants
    SCORE_CORRECT = Decimal("1.0")
    SCORE_INCORRECT = Decimal("-0.25")
    SCORE_SKIP = Decimal("0.0")
    
    # Exam composition
    TOTAL_QUESTIONS = 100
    GAT_COUNT = 70  # 70% General Aptitude Test
    SUBJECT_COUNT = 30  # 30% Subject/Domain Specific
    
    # Timing
    TIME_LIMIT_MINUTES = 120
    TIME_LIMIT_SECONDS = TIME_LIMIT_MINUTES * 60
    AUTO_SAVE_INTERVAL = 5  # Save every N questions
    
    # Weighting algorithm
    FAIL_COUNT_WEIGHT = 2.0
    DAYS_WEIGHT = 1.0
    
    def __init__(self, user_id: UUID, question_pool: List[Dict]):
        """
        Initialize test session.
        
        Args:
            user_id: UUID of the test-taker
            question_pool: Pre-fetched list of questions with stats
                Expected keys: id, category, text, options, correct_answer_idx, 
                            fail_count, last_attempted_at, explanation
        """
        self.session_id = uuid4()
        self.user_id = user_id
        self.question_pool = question_pool
        
        self.questions: List[Dict] = []
        self.answers: List[Dict] = {}  # {question_id: {user_choice_idx, time_spent_sec}}
        
        self.started_at = datetime.utcnow()
        self.ended_at = None
        self.status = "in_progress"
        
        self.score_earned = Decimal("0.0")
        self.score_total = Decimal(str(self.TOTAL_QUESTIONS))
        
        # Track current position in exam
        self.current_question_idx = 0
    
    def _calculate_priority_score(self, fail_count: int, last_attempted_at: datetime) -> float:
        """
        Calculate priority score for weighted selection.
        
        Formula: Priority = (fail_count × 2) + days_since_last_practiced
        
        Higher scores = higher probability of selection (weak areas prioritized)
        """
        days_since = 999  # Default for never-attempted
        if last_attempted_at:
            days_since = (datetime.utcnow() - last_attempted_at).days
        
        return (fail_count * self.FAIL_COUNT_WEIGHT) + (days_since * self.DAYS_WEIGHT)
    
    def _weighted_sample(self, questions: List[Dict], size: int) -> List[Dict]:
        """
        Select questions using weighted random sampling.
        Higher fail_count + longer time since practice = higher probability.
        """
        if len(questions) <= size:
            return questions
        
        # Calculate weights
        weights = []
        for q in questions:
            fail_count = q.get("fail_count", 0)
            last_attempted_at = q.get("last_attempted_at")
            
            # Parse datetime if it's a string
            if isinstance(last_attempted_at, str):
                try:
                    last_attempted_at = datetime.fromisoformat(last_attempted_at.replace("Z", "+00:00"))
                except:
                    last_attempted_at = None
            
            priority = self._calculate_priority_score(fail_count, last_attempted_at)
            # Convert priority to probability weight (ensure > 0)
            weight = max(0.1, priority)  # Min weight of 0.1 to avoid zero-weight
            weights.append(weight)
        
        # Normalize weights
        total_weight = sum(weights)
        if total_weight == 0:
            weights = [1.0] * len(questions)
            total_weight = len(questions)
        
        normalized_weights = [w / total_weight for w in weights]
        
        # Weighted random choice without replacement
        selected = random.choices(questions, weights=normalized_weights, k=size)
        return selected
    
    def generate_questions(self) -> List[Dict]:
        """
        Generate 100-question exam with 70% GAT and 30% Subject.
        Uses weighted random selection to prioritize weak areas.
        
        Returns:
            List of selected questions
        """
        # Separate questions by category
        gat_questions = [q for q in self.question_pool if q.get("category") == "gat"]
        subject_questions = [q for q in self.question_pool if q.get("category") == "subject"]
        
        logger.info(f"Available: {len(gat_questions)} GAT, {len(subject_questions)} Subject")
        
        # Validate availability
        if len(gat_questions) < self.GAT_COUNT:
            logger.warning(f"Only {len(gat_questions)} GAT questions available, need {self.GAT_COUNT}")
        if len(subject_questions) < self.SUBJECT_COUNT:
            logger.warning(f"Only {len(subject_questions)} Subject questions available, need {self.SUBJECT_COUNT}")
        
        # Select questions using weighted sampling
        gat_selected = self._weighted_sample(gat_questions, min(self.GAT_COUNT, len(gat_questions)))
        subject_selected = self._weighted_sample(subject_questions, min(self.SUBJECT_COUNT, len(subject_questions)))
        
        # Combine and shuffle
        all_questions = gat_selected + subject_selected
        random.shuffle(all_questions)
        
        self.questions = all_questions
        logger.info(f"Test session {self.session_id}: Generated {len(all_questions)} questions")
        
        return all_questions
    
    def submit_answer(self, question_id: UUID, user_choice_idx: int, time_spent_sec: int = 0) -> Dict:
        """
        Record answer and calculate points.
        
        Args:
            question_id: UUID of question answered
            user_choice_idx: User's choice (0-3) or None for skip
            time_spent_sec: Seconds spent on this question
        
        Returns:
            {is_correct, points_earned, explanation}
        """
        # Find question
        question = next((q for q in self.questions if q["id"] == question_id), None)
        if not question:
            logger.error(f"Question {question_id} not found in session")
            return {"is_correct": False, "points_earned": 0, "error": "Question not found"}
        
        # Record answer
        is_correct = False
        points = self.SCORE_SKIP
        
        if user_choice_idx is not None:
            is_correct = user_choice_idx == question.get("correct_answer_idx")
            points = self.SCORE_CORRECT if is_correct else self.SCORE_INCORRECT
        
        self.answers[str(question_id)] = {
            "user_choice_idx": user_choice_idx,
            "is_correct": is_correct,
            "points_earned": points,
            "time_spent_sec": time_spent_sec,
            "answered_at": datetime.utcnow().isoformat()
        }
        
        self.score_earned += points
        self.current_question_idx += 1
        
        logger.debug(f"Answer recorded: Q={question_id[:8]}, Correct={is_correct}, Points={points}")
        
        return {
            "is_correct": is_correct,
            "points_earned": float(points),
            "explanation": question.get("explanation", ""),
            "correct_answer_idx": question.get("correct_answer_idx"),
            "total_score": float(self.score_earned)
        }
    
    def end_session(self) -> Dict:
        """
        Finalize session and calculate results.
        
        Returns:
            Session summary with score, pass status, metrics
        """
        self.ended_at = datetime.utcnow()
        self.status = "completed"
        
        # Calculate pass status (50% = 50+ points out of 100)
        pass_threshold = self.score_total / 2
        self.pass_status = self.score_earned >= pass_threshold
        
        # Calculate accuracy
        answered = sum(1 for a in self.answers.values() if a["user_choice_idx"] is not None)
        correct = sum(1 for a in self.answers.values() if a["is_correct"])
        accuracy = (correct / answered * 100) if answered > 0 else 0
        
        # Category breakdown
        category_stats = {}
        for question in self.questions:
            cat = question.get("sub_category", "unknown")
            answer = self.answers.get(str(question["id"]), {})
            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "correct": 0}
            category_stats[cat]["total"] += 1
            if answer.get("is_correct"):
                category_stats[cat]["correct"] += 1
        
        result = {
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "status": self.status,
            "score_earned": float(self.score_earned),
            "score_total": float(self.score_total),
            "percentage": float(self.score_earned / self.score_total * 100) if self.score_total > 0 else 0,
            "pass_status": self.pass_status,
            "pass_threshold": float(pass_threshold),
            "questions_answered": answered,
            "questions_skipped": len(self.questions) - answered,
            "correct_count": correct,
            "accuracy_percent": accuracy,
            "duration_minutes": (self.ended_at - self.started_at).total_seconds() / 60,
            "category_breakdown": category_stats,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat()
        }
        
        logger.info(f"Session {self.session_id} completed: Score={result['score_earned']}/{result['score_total']}, Pass={self.pass_status}")
        
        return result
    
    def get_current_question(self) -> Dict:
        """Get the current question to display."""
        if self.current_question_idx >= len(self.questions):
            return None
        return self.questions[self.current_question_idx]
    
    def get_session_summary(self) -> Dict:
        """Get real-time summary for display during exam."""
        answered = sum(1 for a in self.answers.values() if a["user_choice_idx"] is not None)
        correct = sum(1 for a in self.answers.values() if a["is_correct"])
        
        return {
            "session_id": str(self.session_id),
            "current_question": self.current_question_idx + 1,
            "total_questions": len(self.questions),
            "questions_answered": answered,
            "questions_skipped": len(self.questions) - answered,
            "current_score": float(self.score_earned),
            "correct_count": correct,
            "time_elapsed_sec": (datetime.utcnow() - self.started_at).total_seconds(),
            "time_remaining_sec": max(0, self.TIME_LIMIT_SECONDS - (datetime.utcnow() - self.started_at).total_seconds())
        }


def calculate_exam_statistics(session_result: Dict, historical_questions: List[Dict]) -> Dict:
    """
    Analyze performance and identify weak areas for future sessions.
    
    Args:
        session_result: Output from TestSession.end_session()
        historical_questions: Questions from the session
    
    Returns:
        Lag analysis: sub_categories ranked by failure rate
    """
    lag_analysis = {}
    
    for cat, stats in session_result["category_breakdown"].items():
        if stats["total"] > 0:
            accuracy = stats["correct"] / stats["total"] * 100
            lag_analysis[cat] = {
                "total": stats["total"],
                "correct": stats["correct"],
                "accuracy_percent": accuracy,
                "lag_factor": (100 - accuracy) * stats["total"]  # Weighted by frequency
            }
    
    # Sort by lag factor (highest first = weakest)
    sorted_lags = sorted(lag_analysis.items(), key=lambda x: x[1]["lag_factor"], reverse=True)
    
    return {
        "weak_areas": sorted_lags[:5],  # Top 5 weakest
        "strong_areas": sorted_lags[-5:] if len(sorted_lags) > 5 else [],  # Top 5 strongest
        "all_categories": dict(sorted_lags)
    }
