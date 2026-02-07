-- Create questions table for MOD exam system
-- Run this in Supabase SQL Editor: https://app.supabase.com

CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL CHECK (category IN ('gat', 'subject')),
    sub_category TEXT NOT NULL,
    text TEXT NOT NULL,
    options JSONB NOT NULL,
    correct_answer_idx INTEGER NOT NULL CHECK (correct_answer_idx >= 0 AND correct_answer_idx <= 9),
    explanation TEXT DEFAULT '',
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
CREATE INDEX IF NOT EXISTS idx_questions_sub_category ON questions(sub_category);
CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source);

-- Create user_stats table for tracking performance
CREATE TABLE IF NOT EXISTS user_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    fail_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_attempted_at TIMESTAMPTZ,
    last_correct_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, question_id)
);

-- Create indexes on user_stats
CREATE INDEX IF NOT EXISTS idx_user_stats_user_id ON user_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_user_stats_question_id ON user_stats(question_id);

-- Create sessions table for mock tests
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed')),
    score_earned DECIMAL(10,2) DEFAULT 0,
    score_total DECIMAL(10,2) DEFAULT 100,
    pass_status BOOLEAN,
    questions_answered INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Create session_answers table
CREATE TABLE IF NOT EXISTS session_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    user_choice_idx INTEGER,
    is_correct BOOLEAN,
    points_earned DECIMAL(10,2) DEFAULT 0,
    time_spent_sec INTEGER,
    answered_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes on sessions
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_session_answers_session_id ON session_answers(session_id);

-- Grant permissions (adjust based on your Supabase setup)
-- These are typically auto-configured by Supabase based on Row Level Security policies
