"""
Database operations for PrepMaster AI.
Handles Supabase CRUD for questions, user stats, and sessions.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from uuid import UUID
from decimal import Decimal

from supabase import create_client, Client
from dotenv import load_dotenv
import os

logger = logging.getLogger(__name__)

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


class DatabaseClient:
    """Wrapper around Supabase client with PrepMaster-specific operations."""
    
    def __init__(self):
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # ============= Questions =============
    
    def get_questions_for_session(self, user_id: UUID, limit: int = 1000) -> List[Dict]:
        """
        Fetch all available questions with user stats for weighted selection.
        
        Args:
            user_id: UUID of user (for stats lookup)
            limit: Max questions to fetch
        
        Returns:
            List of questions with fail_count, last_attempted_at, etc.
        """
        try:
            response = self.client.table("questions_with_stats").select("*").limit(limit).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching questions: {e}")
            return []
    
    def get_questions_by_category(self, category: str, limit: int = 100) -> List[Dict]:
        """Fetch questions filtered by category (gat or subject)."""
        try:
            response = (
                self.client.table("questions")
                .select("*")
                .eq("category", category)
                .limit(limit)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching questions by category {category}: {e}")
            return []
    
    def get_random_questions(self, category: str, count: int) -> List[Dict]:
        """Fetch random questions by category."""
        try:
            response = (
                self.client.table("questions")
                .select("*")
                .eq("category", category)
                .limit(count)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching random questions: {e}")
            return []
    
    def upsert_question(self, question: Dict) -> bool:
        """Upsert a single question (insert or update if exists)."""
        try:
            self.client.table("questions").upsert(question).execute()
            return True
        except Exception as e:
            logger.error(f"Error upserting question: {e}")
            return False
    
    def upsert_questions_batch(self, questions: List[Dict], chunk_size: int = 200) -> int:
        """
        Batch upsert questions with chunking.
        
        Args:
            questions: List of question dicts
            chunk_size: Number of questions per upsert call
        
        Returns:
            Total number of questions upserted
        """
        total = 0
        for i in range(0, len(questions), chunk_size):
            chunk = questions[i:i+chunk_size]
            try:
                self.client.table("questions").upsert(chunk).execute()
                total += len(chunk)
                logger.debug(f"Upserted chunk {i//chunk_size + 1}: {len(chunk)} questions")
            except Exception as e:
                logger.error(f"Error upserting chunk: {e}")
        
        logger.info(f"Total questions upserted: {total}")
        return total
    
    # ============= User Stats =============
    
    def get_user_stats(self, user_id: UUID, question_id: Optional[UUID] = None) -> List[Dict]:
        """
        Fetch user stats for specific question or all questions.
        
        Args:
            user_id: UUID of user
            question_id: Optional question UUID (None = all stats for user)
        
        Returns:
            List of user_stats records
        """
        try:
            query = self.client.table("user_stats").select("*").eq("user_id", str(user_id))
            if question_id:
                query = query.eq("question_id", str(question_id))
            response = query.execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching user stats: {e}")
            return []
    
    def update_user_stats(
        self,
        user_id: UUID,
        question_id: UUID,
        is_correct: bool
    ) -> bool:
        """
        Update user stats after answering a question.
        Increments success_count or fail_count, updates last_attempted_at.
        
        Args:
            user_id: UUID of user
            question_id: UUID of question
            is_correct: Whether answer was correct
        
        Returns:
            True if successful
        """
        try:
            # Get existing stats
            existing = self.client.table("user_stats").select("*").match({
                "user_id": str(user_id),
                "question_id": str(question_id)
            }).execute()
            
            if existing.data:
                # Update existing
                stat = existing.data[0]
                update_data = {
                    "fail_count": stat["fail_count"] + (0 if is_correct else 1),
                    "success_count": stat["success_count"] + (1 if is_correct else 0),
                    "last_attempted_at": datetime.utcnow().isoformat()
                }
                if is_correct:
                    update_data["last_correct_at"] = datetime.utcnow().isoformat()
                
                self.client.table("user_stats").update(update_data).eq("id", stat["id"]).execute()
            else:
                # Insert new
                insert_data = {
                    "user_id": str(user_id),
                    "question_id": str(question_id),
                    "fail_count": 0 if is_correct else 1,
                    "success_count": 1 if is_correct else 0,
                    "last_attempted_at": datetime.utcnow().isoformat(),
                    "last_correct_at": datetime.utcnow().isoformat() if is_correct else None
                }
                self.client.table("user_stats").insert(insert_data).execute()
            
            return True
        except Exception as e:
            logger.error(f"Error updating user stats: {e}")
            return False
    
    # ============= Sessions =============
    
    def create_session(
        self,
        user_id: UUID,
        gat_count: int = 70,
        subject_count: int = 30
    ) -> Optional[UUID]:
        """
        Create a new test session record.
        
        Returns:
            Session UUID or None if failed
        """
        try:
            session_data = {
                "user_id": str(user_id),
                "status": "in_progress",
                "score_earned": 0,
                "score_total": 100,
                "questions_answered": 0,
                "gat_count": gat_count,
                "subject_count": subject_count,
                "started_at": datetime.utcnow().isoformat()
            }
            response = self.client.table("sessions").insert(session_data).execute()
            if response.data:
                return UUID(response.data[0]["id"])
            return None
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            return None
    
    def save_session_answer(
        self,
        session_id: UUID,
        question_id: UUID,
        user_choice_idx: Optional[int],
        is_correct: bool,
        points_earned: Decimal,
        time_spent_sec: int
    ) -> bool:
        """Record a single answer in a session."""
        try:
            answer_data = {
                "session_id": str(session_id),
                "question_id": str(question_id),
                "user_choice_idx": user_choice_idx,
                "is_correct": is_correct,
                "points_earned": float(points_earned),
                "time_spent_sec": time_spent_sec,
                "created_at": datetime.utcnow().isoformat()
            }
            self.client.table("session_answers").insert(answer_data).execute()
            return True
        except Exception as e:
            logger.error(f"Error saving session answer: {e}")
            return False
    
    def end_session(
        self,
        session_id: UUID,
        score_earned: Decimal,
        pass_status: bool,
        questions_answered: int
    ) -> bool:
        """Finalize a session."""
        try:
            update_data = {
                "status": "completed",
                "score_earned": float(score_earned),
                "pass_status": pass_status,
                "questions_answered": questions_answered,
                "ended_at": datetime.utcnow().isoformat()
            }
            self.client.table("sessions").update(update_data).eq("id", str(session_id)).execute()
            return True
        except Exception as e:
            logger.error(f"Error ending session: {e}")
            return False
    
    def get_session_history(self, user_id: UUID, limit: int = 10) -> List[Dict]:
        """Fetch user's session history."""
        try:
            response = (
                self.client.table("sessions")
                .select("*")
                .eq("user_id", str(user_id))
                .order("started_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching session history: {e}")
            return []
    
    def get_session_answers(self, session_id: UUID) -> List[Dict]:
        """Fetch all answers for a session."""
        try:
            response = (
                self.client.table("session_answers")
                .select("*")
                .eq("session_id", str(session_id))
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching session answers: {e}")
            return []
    
    # ============= Analytics =============
    
    def get_weak_areas(self, user_id: UUID, top_n: int = 5) -> List[Dict]:
        """
        Get user's weakest sub_categories by fail_count.
        
        Returns:
            List of {sub_category, fail_count, success_count, accuracy_percent}
        """
        try:
            # This is a complex query; for now, fetch all stats and compute locally
            stats = self.get_user_stats(user_id)
            
            # Group by sub_category
            category_stats = {}
            for stat in stats:
                # Fetch question to get sub_category
                q_response = (
                    self.client.table("questions")
                    .select("sub_category")
                    .eq("id", stat["question_id"])
                    .single()
                    .execute()
                )
                if q_response.data:
                    cat = q_response.data["sub_category"]
                    if cat not in category_stats:
                        category_stats[cat] = {"fail": 0, "success": 0}
                    category_stats[cat]["fail"] += stat["fail_count"]
                    category_stats[cat]["success"] += stat["success_count"]
            
            # Calculate accuracy and sort by fail count
            results = []
            for cat, counts in category_stats.items():
                total = counts["fail"] + counts["success"]
                accuracy = (counts["success"] / total * 100) if total > 0 else 0
                results.append({
                    "sub_category": cat,
                    "fail_count": counts["fail"],
                    "success_count": counts["success"],
                    "accuracy_percent": accuracy
                })
            
            results.sort(key=lambda x: x["fail_count"], reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.error(f"Error fetching weak areas: {e}")
            return []
    
    def get_performance_summary(self, user_id: UUID) -> Dict:
        """Get overall performance metrics for user."""
        try:
            sessions = self.get_session_history(user_id)
            
            if not sessions:
                return {
                    "total_sessions": 0,
                    "avg_score": 0,
                    "pass_count": 0,
                    "total_questions_answered": 0
                }
            
            completed = [s for s in sessions if s["status"] == "completed"]
            
            total_questions = sum(s.get("questions_answered", 0) for s in completed)
            pass_count = sum(1 for s in completed if s.get("pass_status"))
            avg_score = sum(s.get("score_earned", 0) for s in completed) / len(completed) if completed else 0
            
            return {
                "total_sessions": len(completed),
                "avg_score": float(avg_score),
                "pass_count": pass_count,
                "pass_rate_percent": (pass_count / len(completed) * 100) if completed else 0,
                "total_questions_answered": total_questions,
                "avg_accuracy": (sum(s.get("questions_answered", 0) for s in completed) / total_questions * 100) if total_questions > 0 else 0
            }
        except Exception as e:
            logger.error(f"Error fetching performance summary: {e}")
            return {}


# Singleton instance
_db_client: Optional[DatabaseClient] = None


def get_database() -> DatabaseClient:
    """Get or create database client singleton."""
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
    return _db_client
