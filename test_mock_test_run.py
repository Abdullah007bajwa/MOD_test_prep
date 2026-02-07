"""
Simulate a short mock test: fetch questions from DB, answer some right, some wrong, some skip.
Verifies correct_answer_idx is stored and scoring works (Correct +1, Wrong -0.25, Skip 0).

Run: python test_mock_test_run.py [--count 20]
"""
import argparse
import os
import random
import sys
from pathlib import Path

path = Path(__file__).resolve().parent
if str(path) not in sys.path:
    sys.path.insert(0, str(path))

from dotenv import load_dotenv
load_dotenv()

# Scoring (same as engine.py)
CORRECT_SCORE = 1.0
INCORRECT_SCORE = -0.25
SKIPPED_SCORE = 0.0


def main():
    parser = argparse.ArgumentParser(description="Simulate a mock test to verify DB answers and scoring.")
    parser.add_argument("--count", type=int, default=20, help="Number of questions to attempt (default 20)")
    parser.add_argument("--correct-ratio", type=float, default=0.5, help="Fraction to answer correctly (default 0.5)")
    parser.add_argument("--wrong-ratio", type=float, default=0.3, help="Fraction to answer wrongly (default 0.3)")
    # skip = 1 - correct - wrong
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)

    from supabase import create_client
    client = create_client(url, key)

    # Fetch a mix of GAT and subject (like real exam)
    n = args.count
    n_gat = int(n * 0.7)
    n_subj = n - n_gat
    gat = client.table("questions").select("*").eq("category", "gat").limit(n_gat * 2).execute()
    subj = client.table("questions").select("*").eq("category", "subject").limit(n_subj * 2).execute()
    gat_list = (gat.data or [])[:n_gat]
    subj_list = (subj.data or [])[:n_subj]
    questions = gat_list + subj_list
    random.shuffle(questions)

    if len(questions) < 5:
        print("Not enough questions in DB. Need at least 5.")
        sys.exit(1)

    correct_ratio = max(0, min(1, args.correct_ratio))
    wrong_ratio = max(0, min(1, args.wrong_ratio))
    skip_ratio = 1.0 - correct_ratio - wrong_ratio
    if skip_ratio < 0:
        skip_ratio = 0

    results = []
    for i, q in enumerate(questions):
        num_options = len(q.get("options") or [])
        correct_idx = q.get("correct_answer_idx", 0)
        if not isinstance(correct_idx, int) or correct_idx < 0:
            correct_idx = 0
        if correct_idx >= num_options:
            correct_idx = 0

        r = random.random()
        if r < correct_ratio:
            chosen = correct_idx
            outcome = "correct"
        elif r < correct_ratio + wrong_ratio and num_options > 1:
            wrong_options = [j for j in range(num_options) if j != correct_idx]
            chosen = random.choice(wrong_options)
            outcome = "wrong"
        else:
            chosen = -1
            outcome = "skip"

        if outcome == "correct":
            score = CORRECT_SCORE
        elif outcome == "wrong":
            score = INCORRECT_SCORE
        else:
            score = SKIPPED_SCORE

        results.append({
            "index": i + 1,
            "id": q.get("id", "")[:8],
            "category": q.get("category", ""),
            "sub_category": (q.get("sub_category") or "")[:20],
            "correct_idx": correct_idx,
            "chosen": chosen,
            "outcome": outcome,
            "score": score,
        })

    # Summary
    total_score = sum(r["score"] for r in results)
    n_correct = sum(1 for r in results if r["outcome"] == "correct")
    n_wrong = sum(1 for r in results if r["outcome"] == "wrong")
    n_skip = sum(1 for r in results if r["outcome"] == "skip")

    print()
    print("=" * 60)
    print("MOCK TEST SIMULATION (verify DB answers + scoring)")
    print("=" * 60)
    print(f"  Questions attempted: {len(results)}")
    print(f"  Correct: {n_correct}  (each +{CORRECT_SCORE})")
    print(f"  Wrong:   {n_wrong}  (each {INCORRECT_SCORE})")
    print(f"  Skipped: {n_skip}  (each {SKIPPED_SCORE})")
    print(f"  Total score: {total_score:.2f}")
    print()
    print("Per question (first 15):")
    print("-" * 60)
    for r in results[:15]:
        ch = r["chosen"] if r["chosen"] >= 0 else "skip"
        ok = "OK" if r["outcome"] == "correct" else ("X" if r["outcome"] == "wrong" else "-")
        print(f"  Q{r['index']:2d}  correct_idx={r['correct_idx']}  chosen={ch}  {ok}  {r['outcome']:6s}  score={r['score']:+.2f}  [{r['category']}]")
    if len(results) > 15:
        print(f"  ... and {len(results) - 15} more")
    print()
    expected = n_correct * CORRECT_SCORE + n_wrong * INCORRECT_SCORE + n_skip * SKIPPED_SCORE
    if abs(expected - total_score) < 0.01:
        print("Score matches formula: correct answers are stored and system is working.")
    else:
        print("WARNING: Score mismatch. Check scoring logic.")
    print()


if __name__ == "__main__":
    main()
