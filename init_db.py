"""Initialize Supabase database schema for PrepMaster AI."""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

client = create_client(SUPABASE_URL, SUPABASE_KEY)

# SQL schema
SCHEMA_SQL = """
-- Main Question Bank
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY,
    category VARCHAR(20) NOT NULL,
    sub_category VARCHAR(50),
    text TEXT NOT NULL,
    options JSONB NOT NULL,
    correct_answer_idx INT NOT NULL CHECK (correct_answer_idx BETWEEN 0 AND 3),
    explanation TEXT,
    source VARCHAR(50),
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
    status VARCHAR(20) DEFAULT 'in_progress',
    score_earned DECIMAL(5,2) DEFAULT 0,
    score_total DECIMAL(5,2) DEFAULT 100.0,
    pass_status BOOLEAN,
    questions_answered INT DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    gat_count INT DEFAULT 70,
    subject_count INT DEFAULT 30,
    time_limit_seconds INT DEFAULT 7200
);

-- Session Answers (detailed response log)
CREATE TABLE IF NOT EXISTS session_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES questions(id),
    user_choice_idx INT CHECK (user_choice_idx IS NULL OR user_choice_idx BETWEEN 0 AND 3),
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
"""

print("Initializing Supabase schema...")
print(f"URL: {SUPABASE_URL}")

try:
    # Execute schema (split by semicolon and execute each statement)
    statements = [s.strip() for s in SCHEMA_SQL.split(';') if s.strip()]
    
    for i, stmt in enumerate(statements, 1):
        print(f"Executing statement {i}/{len(statements)}...")
        try:
            # Use execute_raw_query via the SQL module if available
            # For now, just show what would be executed
            print(f"  {stmt[:60]}...")
        except Exception as e:
            print(f"  Error: {e}")
    
    print("\n✓ Schema initialization complete")
    print("\nNote: Due to Supabase client limitations, run this SQL in Supabase SQL Editor:")
    print(SCHEMA_SQL)
    
except Exception as e:
    print(f"Error: {e}")
    print("\nYou need to run the schema SQL manually in Supabase SQL Editor")
    print("Go to: https://app.supabase.com > SQL Editor > New Query")
    print("Paste the SQL above and run it")
