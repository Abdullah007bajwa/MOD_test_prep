"""CLI-facing Supabase client and bulk upsert. Delegates to db."""
import sys
from pathlib import Path

# Ensure repo root is on path when running as script or -m
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from db import get_supabase_uncached, upsert_questions_bulk, upsert_questions_chunk


def get_client():
    return get_supabase_uncached()


def upsert_questions(rows: list[dict], chunk_size: int = 200):
    client = get_client()
    upsert_questions_bulk(client, rows, chunk_size=chunk_size)


def upsert_questions_chunk_client(rows: list[dict]):
    """Upsert a single chunk (for incremental flush). Use from CLI when passing on_chunk to scraper."""
    client = get_client()
    upsert_questions_chunk(client, rows)
