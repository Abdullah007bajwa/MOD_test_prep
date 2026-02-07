-- Migration: Allow more than 4 options and correct_answer_idx > 3 (e.g. for gotest.com.pk).
-- Run in Supabase SQL Editor if your questions table still has CHECK (correct_answer_idx BETWEEN 0 AND 3).

-- Drop existing check on questions.correct_answer_idx (name may vary; try both)
ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_correct_answer_idx_check;
ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_correct_answer_idx_range_check;

ALTER TABLE questions ADD CONSTRAINT questions_correct_answer_idx_check
  CHECK (correct_answer_idx >= 0 AND correct_answer_idx <= 9);

-- If you have session_answers with user_choice_idx 0-3 only:
ALTER TABLE session_answers DROP CONSTRAINT IF EXISTS session_answers_user_choice_idx_check;
ALTER TABLE session_answers ADD CONSTRAINT session_answers_user_choice_idx_check
  CHECK (user_choice_idx IS NULL OR (user_choice_idx >= 0 AND user_choice_idx <= 9));
