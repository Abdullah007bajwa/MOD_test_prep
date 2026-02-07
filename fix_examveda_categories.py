"""
One-off fix: set category='gat' for examveda questions that are GAT topics
(English, GK, CA, Logical Reasoning, Grammar, Analogies) but were wrongly stored as 'subject'.

Run once: python fix_examveda_categories.py [--dry-run]
"""
import argparse
import os
import sys
from pathlib import Path

path = Path(__file__).resolve().parent
if str(path) not in sys.path:
    sys.path.insert(0, str(path))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="Print total examveda MCQs in DB and by category, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Only print how many would be updated")
    parser.add_argument("--debug", action="store_true", help="Print distinct sub_category values for examveda+subject")
    args = parser.parse_args()
    dry_run = args.dry_run
    debug = args.debug
    count_only = args.count
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)
    client = create_client(url, key)

    if count_only:
        r = client.table("questions").select("id", "category").eq("source", "examveda").limit(50000).execute()
        data = r.data or []
        total = len(data)
        gat = sum(1 for row in data if (row.get("category") or "").strip().lower() == "gat")
        subject = sum(1 for row in data if (row.get("category") or "").strip().lower() == "subject")
        print("Examveda MCQs in DB:")
        print(f"  Total:   {total}")
        print(f"  GAT:     {gat}")
        print(f"  Subject: {subject}")
        return

    # GAT = English, GK, CA, Logical Reasoning, Grammar, Analogies, etc.
    # Subject = CS/AI only. So examveda rows that are not CS topics should be gat.
    gat_keywords = ("english", "grammar", "analogies", "general_knowledge", "current_affairs", "logical_reasoning", "gk", "ca", "lr")
    subject_keywords = ("data_structure", "oops", "operating_system", "networking", "software_engineering", "compiler", "opencv", "algorithm", "computer_fundamental")

    # Fetch examveda rows that are currently subject (request enough rows)
    r = client.table("questions").select("id", "sub_category").eq("source", "examveda").eq("category", "subject").limit(50000).execute()
    rows = r.data or []
    if not rows:
        print("No examveda questions with category='subject' found. Nothing to fix.")
        return

    if debug:
        from collections import Counter
        subs = Counter((row.get("sub_category") or "").strip() for row in rows)
        print("Distinct sub_category for examveda+subject:")
        for name, count in sorted(subs.items(), key=lambda x: -x[1]):
            print(f"  {count:6d}  {name!r}")
        return

    # Fix: treat as GAT unless sub_category clearly looks like CS/AI subject
    to_fix = []
    for row in rows:
        sub = (row.get("sub_category") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not sub:
            continue
        if any(k in sub for k in subject_keywords):
            continue
        # Everything else from examveda (English, GK, CA, LR, Grammar, etc.) -> gat
        to_fix.append(row["id"])
    if not to_fix:
        print("No rows to update.")
        return

    print(f"Found {len(to_fix)} examveda questions to set category='gat'.")
    if dry_run:
        print("Dry run. Run without --dry-run to apply.")
        return

    # Update in chunks
    chunk_size = 200
    updated = 0
    for i in range(0, len(to_fix), chunk_size):
        chunk_ids = to_fix[i : i + chunk_size]
        client.table("questions").update({"category": "gat"}).in_("id", chunk_ids).execute()
        updated += len(chunk_ids)
        print(f"Updated {updated}/{len(to_fix)} rows to category=gat")

    print(f"Done. Set category='gat' for {updated} examveda questions.")

if __name__ == "__main__":
    main()
