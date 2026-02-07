"""
Set category by source:
  GAT     = examveda, pakmcqs, indiabix
  Subject = sanfoundry only

Run: python fix_category_by_source.py [--dry-run]
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

GAT_SOURCES = ("examveda", "pakmcqs", "indiabix")
SUBJECT_SOURCES = ("sanfoundry",)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be updated")
    args = parser.parse_args()
    dry_run = args.dry_run

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)
    client = create_client(url, key)

    # Fetch all questions (id, category, source) in pages
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        r = (
            client.table("questions")
            .select("id", "category", "source")
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
        print(f"  Fetched {len(all_rows)} rows...", file=sys.stderr)

    to_gat = []   # ids that should be category='gat'
    to_subject = []  # ids that should be category='subject'
    for row in all_rows:
        src = (row.get("source") or "").strip().lower()
        current = (row.get("category") or "").strip().lower()
        qid = row.get("id")
        if not qid:
            continue
        if src in GAT_SOURCES:
            if current != "gat":
                to_gat.append(qid)
        elif src in SUBJECT_SOURCES:
            if current != "subject":
                to_subject.append(qid)
        # unknown source: leave as-is

    print()
    print("Category by source: GAT = examveda, pakmcqs, indiabix  |  Subject = sanfoundry")
    print(f"  Set to GAT:     {len(to_gat)} questions (examveda/pakmcqs/indiabix)")
    print(f"  Set to Subject: {len(to_subject)} questions (sanfoundry)")
    if dry_run:
        print("Dry run. Run without --dry-run to apply.")
        return

    chunk_size = 200
    for i in range(0, len(to_gat), chunk_size):
        chunk = to_gat[i : i + chunk_size]
        client.table("questions").update({"category": "gat"}).in_("id", chunk).execute()
        print(f"  Updated {min(i + chunk_size, len(to_gat))}/{len(to_gat)} -> gat")
    for i in range(0, len(to_subject), chunk_size):
        chunk = to_subject[i : i + chunk_size]
        client.table("questions").update({"category": "subject"}).in_("id", chunk).execute()
        print(f"  Updated {min(i + chunk_size, len(to_subject))}/{len(to_subject)} -> subject")
    print("Done.")

if __name__ == "__main__":
    main()
