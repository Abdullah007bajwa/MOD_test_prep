"""Ingest .jsonl: map topic -> sub_category, Grammar/Analogies -> gat; bulk UPSERT into questions."""
import json
import argparse
import logging
import random
from pathlib import Path
from uuid import uuid5, NAMESPACE_DNS

from db import get_supabase_uncached, upsert_questions_bulk, delete_questions_by_source

DEFAULT_JSONL = Path(__file__).resolve().parent / "examveda_all_topics_20260110_181441.jsonl"

# GAT = General Aptitude: English, GK, CA, Logical Reasoning, Grammar, Analogies, etc.
# Subject = CS/AI only (data structures, OOP, OS, networking, etc.)
# So we treat examveda as GAT unless the topic is clearly a CS subject.
SUBJECT_TOPICS = {
    "data structures", "data_structures", "oops", "operating system", "operating_system",
    "networking", "software engineering", "compilers", "computer fundamentals",
    "opencv", "ai_opencv", "algorithms",
}


def topic_to_category(topic: str) -> str:
    """Map topic to category: CS/AI topics -> subject; everything else (English, GK, CA, LR, Grammar, etc.) -> gat."""
    t = (topic or "").strip().lower().replace("-", "_").replace(" ", "_")
    if t in SUBJECT_TOPICS:
        return "subject"
    # Normalize for partial match (e.g. "Logical Reasoning" -> logical_reasoning)
    for subj in SUBJECT_TOPICS:
        if subj in t or t in subj:
            return "subject"
    return "gat"


def parse_line(line: str) -> dict | None:
    """Parse one JSONL line into a questions row. Returns None if invalid/skip."""
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    question_id = raw.get("question_id")
    if not question_id:
        return None
    topic = (raw.get("topic") or "").strip()
    text = raw.get("text") or raw.get("question_text") or ""
    options = raw.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return None
    correct_option = raw.get("correct_option", 0)
    if not isinstance(correct_option, int) or correct_option < 0:
        correct_option = 0
    if correct_option >= len(options):
        correct_option = 0
    # DB allows 2–10 options; keep as-is (no truncation). Cap at 10 for consistency.
    if len(options) > 10:
        options = options[:10]
        if correct_option >= 10:
            correct_option = 9
    steps = raw.get("explanation_steps") or []
    explanation = " ".join(steps) if isinstance(steps, list) else str(steps)

    uid = str(uuid5(NAMESPACE_DNS, question_id))
    return {
        "id": uid,
        "category": topic_to_category(topic),
        "sub_category": topic or "unknown",
        "text": text,
        "options": options,
        "correct_answer_idx": correct_option,
        "explanation": explanation[:50000] if explanation else "",
        "source": "examveda",
    }


def load_and_transform(path: Path):
    """Read JSONL and yield transformed question rows."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = parse_line(line)
            if row:
                yield row


def run_import(jsonl_path: Path | None = None, chunk_size: int = 200, dry_run: bool = False, replace: bool = False):
    path = jsonl_path or DEFAULT_JSONL
    if not path.exists():
        raise FileNotFoundError(f"JSONL not found: {path}")
    rows = list(load_and_transform(path))
    if dry_run:
        print(f"Dry run: would upsert {len(rows)} questions from {path}")
        if rows:
            print("Sample row:", rows[0])
        return
    client = get_supabase_uncached()
    if replace:
        delete_questions_by_source(client, "examveda")
        print("Deleted existing examveda questions")
    upsert_questions_bulk(client, rows, chunk_size=chunk_size)
    print(f"Upserted {len(rows)} questions from {path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Import examveda JSONL into Supabase questions.")
    parser.add_argument(
        "jsonl",
        nargs="?",
        default=None,
        help=f"Path to .jsonl (default: {DEFAULT_JSONL})",
    )
    parser.add_argument("--chunk-size", type=int, default=200, help="Upsert chunk size (default 200)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not upsert")
    parser.add_argument("--replace", action="store_true", help="Delete existing examveda questions, then upsert (fresh import)")
    args = parser.parse_args()
    path = Path(args.jsonl) if args.jsonl else DEFAULT_JSONL
    run_import(jsonl_path=path, chunk_size=args.chunk_size, dry_run=args.dry_run, replace=args.replace)
