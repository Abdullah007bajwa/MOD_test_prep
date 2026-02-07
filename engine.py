"""Pure exam logic: scoring, weighting, 70/30 distribution. No UI."""
# Scoring: correct +1.0, incorrect -0.25, skipped 0.0
# Priority = (fail_count * 2) + days_since_last_practiced

CORRECT_SCORE = 1.0
INCORRECT_SCORE = -0.25
SKIPPED_SCORE = 0.0
EXAM_TOTAL = 100
GAT_RATIO = 0.7
SUBJECT_RATIO = 0.3
EXAM_DURATION_MINUTES = 120
