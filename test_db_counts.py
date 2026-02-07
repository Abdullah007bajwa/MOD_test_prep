"""
Report total MCQs in DB with counts by category, sub_category, and source.
Run: python test_db_counts.py
      python test_db_counts.py --under 100   # list sub_categories with fewer than N MCQs and their sources
"""
import argparse
import os
import sys
from pathlib import Path
from collections import Counter, defaultdict

path = Path(__file__).resolve().parent
if str(path) not in sys.path:
    sys.path.insert(0, str(path))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--under", type=int, default=None, metavar="N", help="Only list sub_categories with count < N and their sources")
    args = parser.parse_args()
    under_n = args.under

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)
    client = create_client(url, key)

    # Fetch all questions (id, category, sub_category, source) in chunks (Supabase default limit often 1000)
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        r = (
            client.table("questions")
            .select("id", "category", "sub_category", "source")
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

    total = len(all_rows)
    by_category = Counter((row.get("category") or "").strip() or "(blank)" for row in all_rows)
    by_sub = Counter((row.get("sub_category") or "").strip() or "(blank)" for row in all_rows)
    by_source = Counter((row.get("source") or "").strip() or "(blank)" for row in all_rows)

    # Cross: (category, sub_category, source) for a compact table
    cross = defaultdict(int)
    sub_to_sources = defaultdict(lambda: defaultdict(int))  # sub_category -> { source: count }
    for row in all_rows:
        c = (row.get("category") or "").strip() or "(blank)"
        s = (row.get("sub_category") or "").strip() or "(blank)"
        src = (row.get("source") or "").strip() or "(blank)"
        cross[(c, s, src)] += 1
        sub_to_sources[s][src] += 1

    if under_n is not None:
        print()
        print(f"Sub-categories with fewer than {under_n} MCQs (current sources):")
        print("-" * 70)
        for sub, count in sorted(by_sub.items(), key=lambda x: (x[1], x[0])):
            if count >= under_n:
                continue
            sources = sub_to_sources.get(sub, {})
            src_str = ", ".join(f"{s}({n})" for s, n in sorted(sources.items(), key=lambda x: -x[1]))
            print(f"  {count:4d}  {sub!r}")
            print(f"         sources: {src_str}")
        print()
        return

    print()
    print("=" * 60)
    print("MCQ COUNTS IN DB")
    print("=" * 60)
    print(f"\nTotal MCQs: {total}")
    print("\n--- By category ---")
    for name, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {count:6d}  {name!r}")
    print("\n--- By sub_category ---")
    for name, count in sorted(by_sub.items(), key=lambda x: -x[1]):
        print(f"  {count:6d}  {name!r}")
    print("\n--- By source ---")
    for name, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {count:6d}  {name!r}")
    print("\n--- By category + sub_category + source ---")
    for (cat, sub, src), count in sorted(cross.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {count:6d}  category={cat!r}  sub_category={sub!r}  source={src!r}")
    print()

if __name__ == "__main__":
    main()
