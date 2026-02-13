"""Supabase CRUD. Client is cached via Streamlit."""
import logging
import os
from uuid import UUID

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def _env_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


@st.cache_resource
def get_supabase() -> Client:
    return _env_client()


def get_supabase_uncached() -> Client:
    """For CLI/scripts (no Streamlit context)."""
    return _env_client()


def upsert_questions_chunk(client: Client, rows: list[dict]):
    """Upsert a single chunk (e.g. for incremental flush). Dedupes by id within the chunk."""
    if not rows:
        return
    by_id = {r["id"]: r for r in rows}
    chunk = list(by_id.values())
    log = logging.getLogger(__name__)
    log.info("Upserting chunk (%d rows)", len(chunk))
    client.table("questions").upsert(chunk, on_conflict="id").execute()


def upsert_questions_bulk(client: Client, rows: list[dict], chunk_size: int = 200):
    """Bulk upsert into questions. Rows must include 'id' (uuid). Dedupes by id so no chunk has duplicates (avoids Postgres ON CONFLICT error)."""
    n_before = len(rows)
    by_id = {r["id"]: r for r in rows}
    rows = list(by_id.values())
    if len(rows) < n_before:
        logging.getLogger(__name__).info("Deduped questions by id: %d -> %d", n_before, len(rows))
    n_chunks = (len(rows) + chunk_size - 1) // chunk_size
    log = logging.getLogger(__name__)
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        chunk_num = i // chunk_size + 1
        log.info("Upserting chunk %d/%d (%d rows)", chunk_num, n_chunks, len(chunk))
        client.table("questions").upsert(chunk, on_conflict="id").execute()


# --- Questions ---

def get_questions(limit: int | None = None):
    q = get_supabase().table("questions").select("*")
    if limit:
        q = q.limit(limit)
    return q.execute()


def get_question_by_id(question_id: UUID | str):
    return get_supabase().table("questions").select("*").eq("id", str(question_id)).single().execute()


def get_questions_by_category(category: str, limit: int | None = None):
    q = get_supabase().table("questions").select("*").eq("category", category)
    if limit:
        q = q.limit(limit)
    return q.execute()


def get_questions_by_subcategory(category: str, sub_category: str, limit: int | None = None):
    """Get questions filtered by both category and sub_category."""
    q = get_supabase().table("questions").select("*").eq("category", category).eq("sub_category", sub_category)
    if limit:
        q = q.limit(limit)
    return q.execute()


def get_subcategory_counts(category: str | None = None):
    """Returns dict of {sub_category: count} for given category, or all categories if None."""
    client = get_supabase()
    counts = {}
    
    try:
        # Fetch all questions with category and sub_category
        all_rows = []
        page_size = 1000
        offset = 0
        while True:
            query = client.table("questions").select("category", "sub_category")
            if category:
                query = query.eq("category", category)
            r = query.range(offset, offset + page_size - 1).execute()
            data = r.data or []
            if not data:
                break
            all_rows.extend(data)
            if len(data) < page_size:
                break
            offset += page_size
        
        # Count by sub_category
        from collections import Counter
        sub_cats = [row.get("sub_category") or "(blank)" for row in all_rows]
        counts = dict(Counter(sub_cats))
    except Exception as e:
        logging.getLogger(__name__).error(f"Error getting subcategory counts: {e}")
    
    return counts


def get_subcategories_by_category(category: str):
    """Returns list of unique subcategories for given category."""
    client = get_supabase()
    try:
        # Fetch distinct sub_categories
        all_rows = []
        page_size = 1000
        offset = 0
        while True:
            r = (
                client.table("questions")
                .select("sub_category")
                .eq("category", category)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            data = r.data or []
            if not data:
                break
            all_rows.extend(data)
            if len(data) < page_size:
                break
            offset += page_size
        
        # Get unique subcategories
        subcategories = sorted(set(row.get("sub_category") or "" for row in all_rows if row.get("sub_category")))
        return [s for s in subcategories if s]  # Filter out empty strings
    except Exception as e:
        logging.getLogger(__name__).error(f"Error getting subcategories: {e}")
        return []


def get_question_counts():
    """Returns dict with total, gat, subject counts (for dashboard)."""
    client = get_supabase()
    out = {"total": 0, "gat": 0, "subject": 0}
    for cat in ("gat", "subject"):
        try:
            r = client.table("questions").select("id", count="exact").eq("category", cat).limit(0).execute()
            out[cat] = getattr(r, "count", None) or len(r.data or [])
        except Exception:
            # Fallback: fetch ids in batches (Supabase default limit often 1000)
            r = client.table("questions").select("id").eq("category", cat).limit(20000).execute()
            out[cat] = len(r.data or [])
    out["total"] = out["gat"] + out["subject"]
    return out


def delete_questions_by_source(client: Client, source: str):
    """Delete all questions with the given source (e.g. 'examveda')."""
    client.table("questions").delete().eq("source", source).execute()


# --- User stats ---

def get_user_stats(question_id: UUID | str | None = None):
    q = get_supabase().table("user_stats").select("*")
    if question_id is not None:
        q = q.eq("question_id", str(question_id))
    return q.execute()


def upsert_user_stat(question_id: UUID | str, fail_count: int, success_count: int, last_practiced_at: str):
    row = {
        "question_id": str(question_id),
        "fail_count": fail_count,
        "success_count": success_count,
        "last_practiced_at": last_practiced_at,
    }
    return get_supabase().table("user_stats").upsert(row, on_conflict="question_id").execute()


# --- Sessions ---

def create_session(start_time: str, total_score: float = 0.0, category_breakdown: dict | None = None):
    row = {
        "start_time": start_time,
        "total_score": total_score,
        "category_breakdown": category_breakdown or {},
    }
    return get_supabase().table("sessions").insert(row).execute()


def update_session(session_id: UUID | str, total_score: float, category_breakdown: dict):
    return (
        get_supabase()
        .table("sessions")
        .update({"total_score": total_score, "category_breakdown": category_breakdown})
        .eq("id", str(session_id))
        .execute()
    )


def get_sessions(limit: int = 50):
    return get_supabase().table("sessions").select("*").order("start_time", desc=True).limit(limit).execute()
