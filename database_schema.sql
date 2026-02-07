-- PrepMaster AI Database Schema (Supabase PostgreSQL)
-- Run this in Supabase SQL Editor to initialize the system

-- Main Question Bank
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY,
    category VARCHAR(20) NOT NULL, -- 'gat' or 'subject'
    sub_category VARCHAR(50),
    text TEXT NOT NULL,
    options JSONB NOT NULL, -- 2-10 options: ["opt1", "opt2", ...]
    correct_answer_idx INT NOT NULL CHECK (correct_answer_idx >= 0 AND correct_answer_idx <= 9),
    explanation TEXT,
    source VARCHAR(50), -- indiabix, pakmcqs, sanfoundry, examveda
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(text)
);

-- User Performance Tracking
CREATE TABLE IF NOT EXISTS user_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    fail_count INT DEFAULT 0,
    success_count INT DEFAULT 0,
    last_attempted_at TIMESTAMPTZ,
    last_correct_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, question_id)
);

-- Exam Sessions
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    status VARCHAR(20) DEFAULT 'in_progress', -- in_progress, completed, abandoned
    score_earned DECIMAL(5,2) DEFAULT 0,
    score_total DECIMAL(5,2) DEFAULT 100.0,
    pass_status BOOLEAN,
    questions_answered INT DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    gat_count INT DEFAULT 70,
    subject_count INT DEFAULT 30,
    time_limit_seconds INT DEFAULT 7200 -- 120 minutes
);

-- Session Answers (detailed response log)
CREATE TABLE IF NOT EXISTS session_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES questions(id),
    user_choice_idx INT CHECK (user_choice_idx IS NULL OR (user_choice_idx >= 0 AND user_choice_idx <= 9)),
    is_correct BOOLEAN,
    points_earned DECIMAL(5,2),
    time_spent_sec INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
CREATE INDEX IF NOT EXISTS idx_questions_sub_category ON questions(sub_category);
CREATE INDEX IF NOT EXISTS idx_user_stats_user_id ON user_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_user_stats_question_id ON user_stats(question_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_session_answers_session_id ON session_answers(session_id);

-- Function to calculate priority score for weighted selection
CREATE OR REPLACE FUNCTION calculate_priority(fail_count INT, last_practiced_at TIMESTAMPTZ)
RETURNS FLOAT AS $$
BEGIN
    RETURN (fail_count * 2)::FLOAT + COALESCE(EXTRACT(DAY FROM NOW() - last_practiced_at), 999)::FLOAT;
END;
$$ LANGUAGE plpgsql;

-- View for easy question querying with stats
CREATE OR REPLACE VIEW questions_with_stats AS
SELECT 
    q.id,
    q.category,
    q.sub_category,
    q.text,
    q.options,
    q.correct_answer_idx,
    q.explanation,
    q.source,
    COALESCE(us.fail_count, 0) as fail_count,
    COALESCE(us.success_count, 0) as success_count,
    us.last_attempted_at,
    COALESCE(us.last_attempted_at, q.created_at) as practice_date,
    (COALESCE(us.fail_count, 0) * 2)::FLOAT + COALESCE(EXTRACT(DAY FROM NOW() - us.last_attempted_at), 999)::FLOAT as priority_score
FROM questions q
LEFT JOIN user_stats us ON q.id = us.question_id
WHERE (us.user_id::uuid = auth.uid() OR us IS NULL);
