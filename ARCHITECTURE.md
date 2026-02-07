# PrepMaster AI - Architecture & Implementation Summary

## System Overview

PrepMaster AI is a weighted learning exam platform that prioritizes weak areas through intelligent question selection. It separates data ingestion from runtime processing to handle ephemeral deployments on Render.

### Key Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     Streamlit Frontend (app.py)                 │
│  Dashboard │ Mock Test │ Review │ Settings                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│              Test Engine (src/engine.py)                        │
│  TestSession: Weighted Q selection, Scoring, Session Manager   │
│  • 70/30 GAT/Subject split                                      │
│  • Priority = (fail_count × 2) + days_since_practiced          │
│  • Scoring: +1.0 correct, -0.25 incorrect, 0.0 skip           │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│           Database Client (src/database.py)                     │
│  CRUD for: questions, user_stats, sessions, session_answers    │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│           Supabase PostgreSQL (Cloud Persistence)               │
│  Schema: questions, user_stats, sessions, session_answers      │
│  Views: questions_with_stats (for weighted selection)          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implemented Components

### 1. ✅ **Core Engine** (`src/engine.py`)

**TestSession Class:**
- Manages single mock test session
- Weighted random question selection (prioritizes weak areas)
- Real-time scoring with penalties
- Session lifecycle (start → answer → review → end)

**Key Methods:**
```python
generate_questions()           # 70 GAT + 30 Subject with weighting
submit_answer()                # Record answer, calculate points
end_session()                  # Finalize, calculate pass/fail
get_current_question()         # Display question to user
get_session_summary()          # Real-time stats for UI
```

**Scoring Formula:**
- Correct: +1.0
- Incorrect: -0.25
- Skip: 0.0
- Pass: ≥50 points (50% out of 100)

**Weighting Algorithm:**
```
Priority = (fail_count × 2) + (days_since_last_practiced × 1)
Higher priority = higher probability in weighted random selection
Ensures weak areas appear 3x more often than mastered ones
```

---

### 2. ✅ **Database Client** (`src/database.py`)

**DatabaseClient Class:**

**Question Operations:**
- `get_questions_for_session()` - Fetch all questions with stats
- `get_questions_by_category(category)` - GAT or Subject filter
- `upsert_question()` - Insert/update single
- `upsert_questions_batch()` - Batch upsert with chunking

**User Stats Operations:**
- `get_user_stats()` - Fetch stats for user/question
- `update_user_stats()` - Increment fail/success counts

**Session Operations:**
- `create_session()` - Initialize test session
- `save_session_answer()` - Record individual answer
- `end_session()` - Finalize session
- `get_session_history()` - User's past tests

**Analytics:**
- `get_weak_areas()` - Top N weakest categories
- `get_performance_summary()` - Overall metrics

---

### 3. ✅ **Data Scrapers** (HAR/JSONL Parsers)

#### **Sanfoundry Logical Reasoning** (`src/sanfoundry_subject_scraper.py`)
- **Status**: ✅ 9 questions extracted
- **Source**: www.sanfoundry.com.har
- **Category**: gat
- **Sub-category**: coding_decoding
- **Parser**: `.entry-content` → numbered questions, options, `.collapseanswer`

#### **PakMCQs Current Affairs & GK** (`src/pakmcqs_har_scraper.py`)
- **Status**: ✅ 10 questions extracted
- **Source**: pakmcqs.com.har
- **Category**: gat
- **Sub-categories**: current_affairs, general_knowledge
- **Parser**: `<article class="l-post">` → first `<strong>` for answer

#### **IndiaBIX Logical Reasoning** (`src/indiabix_scraper.py`)
- **Status**: ✅ 83 questions extracted (19 topics)
- **Source**: Live HTTP or HAR
- **Category**: gat
- **Sub-categories**: 19 logical reasoning topics
- **Parser**: `.bix-div-container` → `.bix-td-qtxt`, `.bix-tbl-options`

#### **Examveda JSONL** (`importer.py`)
- **Status**: ✅ 12,131 questions available
- **Source**: examveda_all_topics_*.jsonl
- **Category**: gat
- **Sub-category**: english, grammar
- **Parser**: JSONL with structured fields

---

### 4. ✅ **Database Schema** (`database_schema.sql`)

**Tables:**
- `questions`: Main question bank (UUID primary, category, sub_category, options JSONB, correct_idx, explanation)
- `user_stats`: Performance tracking (fail_count, success_count, last_attempted_at)
- `sessions`: Test sessions (status, score, started_at, ended_at)
- `session_answers`: Detailed response log (user_choice_idx, is_correct, time_spent_sec)

**Indexes**: Optimized for fast category/user lookups

**View**: `questions_with_stats` - Questions with user performance metrics (for weighted selection)

**Function**: `calculate_priority()` - PG function for priority score calculation

---

### 5. ✅ **Configuration** (`.cursorrules`)

Established system ground truth:
- Scoring rules: +1.0/-0.25/0.0
- Exam composition: 100 questions (70 GAT, 30 Subject)
- Weighting algorithm: (fail_count × 2) + days_since_practiced
- Data source priorities and parsing rules
- Quality gates (min lengths, required fields, deduplication)

---

## Data Pipeline Status

```
┌─────────────────────┐
│   Examveda JSONL    │  ✅ 12,131 questions (English/Grammar)
│  (importer.py)      │
└──────────┬──────────┘
           │
┌──────────▼──────────────┐
│  IndiaBIX (19 topics)   │  ✅ 83 questions (Logical Reasoning)
│  (src/indiabix_scraper) │
└──────────┬──────────────┘
           │
┌──────────▼──────────────┐
│  PakMCQs (Current/GK)   │  ✅ 10 questions (Current Affairs/GK)
│  (src/pakmcqs_har...)   │
└──────────┬──────────────┘
           │
┌──────────▼──────────────┐
│  Sanfoundry Logical     │  ✅ 9 questions (Logical Reasoning)
│  (src/sanfoundry...)    │
└──────────┬──────────────┘
           │
     GAT Pool: ~12,100+ questions (70%)
    Subject Pool: TBD (needs Sanfoundry CS topics)

     TOTAL DATABASE: ~12,100+ questions ready
```

---

## Remaining Work

### 1. **Subject Questions (30% Requirement)**
- **Issue**: Sanfoundry CS topics blocked by Cloudflare IP ban
- **Alternative**: Use examveda JSONL subject categories (if available)
- **Status**: ⏳ Needs investigation or manual capture

### 2. **Streamlit Frontend** (NOT YET BUILT)
```
app.py                    # Multi-page router
├── pages/dashboard.py    # Lag heatmap, performance trends
├── pages/mock_test.py    # 120-min timer, live scoring
├── pages/review.py       # Post-exam detailed review
└── pages/settings.py     # User preferences, history
```

### 3. **Authentication** (NOT YET BUILT)
- User login/signup via Supabase Auth
- Session state management

### 4. **Full Integration Testing**
- End-to-end: Scraper → DB → Engine → Frontend
- Load testing on mock exam

---

## Quick Start (Dev)

### 1. Initialize Database
```bash
# Run schema in Supabase SQL Editor
psql -d your_supabase_db < database_schema.sql
```

### 2. Load Questions
```bash
cd /e/MOD
python importer.py --dry-run
python -m src.indiabix_scraper --max-pages 5 --dry-run
python -m src.pakmcqs_har_scraper --dry-run
python -m src.sanfoundry_subject_scraper --dry-run

# If results look good, upsert to DB
./run_scrapers.ps1 -Upsert
```

### 3. Test Engine (Python)
```python
from src.database import get_database
from src.engine import TestSession
from uuid import uuid4

db = get_database()
user_id = uuid4()

# Fetch questions
questions = db.get_questions_for_session(user_id)

# Create test
test = TestSession(user_id, questions)
test.generate_questions()

# Simulate answers
for q in test.questions[:10]:
    result = test.submit_answer(q["id"], user_choice_idx=0, time_spent_sec=30)
    print(f"Q: {result['is_correct']}, Score: {result['total_score']}")

# End test
summary = test.end_session()
print(summary)
```

### 4. Deploy to Render
```bash
git add .
git commit -m "PrepMaster AI - Core engine + database"
git push origin main

# In Render dashboard:
# - Connect repo
# - Build: pip install -r requirements.txt
# - Start: streamlit run app.py --server.port=$PORT
# - Set SUPABASE_URL, SUPABASE_KEY environment vars
```

---

## File Structure

```
e:/MOD/
├── .cursorrules                          # System ground truth
├── .env                                  # Supabase credentials
├── database_schema.sql                   # PostgreSQL schema
├── requirements.txt                      # Python dependencies
├── app.py                                # Streamlit entry (TODO)
├── importer.py                           # Examveda JSONL parser
├── db.py                                 # Original Supabase wrapper
├── db_manager.py                         # CLI wrapper
├── run_scrapers.ps1                      # Scraper orchestration
│
├── src/
│   ├── __init__.py
│   ├── engine.py                         # ✅ TestSession, scoring
│   ├── database.py                       # ✅ DatabaseClient
│   ├── indiabix_scraper.py              # ✅ 19 topics, live HTTP
│   ├── pakmcqs_har_scraper.py           # ✅ GAT current/gk
│   ├── sanfoundry_subject_scraper.py    # ✅ Logical reasoning
│   ├── pakmcqs_live_scraper.py          # Live HTTP fallback
│   └── sanfoundry_live_scraper.py       # Live HTTP fallback
│
├── pakmcqs.com.har                       # Question source
├── www.indiabix.com.har                  # Question source
├── www.sanfoundry.com.har                # Question source
└── examveda_all_topics_*.jsonl           # Question source (12,131 qs)
```

---

## Next Steps (Frontend)

1. **Create `app.py`** with multi-page Streamlit router
2. **Implement `pages/mock_test.py`** with 120-min timer
3. **Implement `pages/dashboard.py`** with Plotly heatmaps
4. **Add Supabase Auth** for user login
5. **Deploy to Render** with GitHub integration

---

## Architecture Principles

1. **Separation of Concerns**: Engine (logic) ≠ Database (persistence) ≠ Frontend (UI)
2. **Weighted Learning**: Weak areas prioritized in question selection
3. **Cloud Persistence**: All state in Supabase (handles Render ephemeral storage)
4. **Batch Processing**: Chunked upserts to handle large question volumes
5. **Deterministic IDs**: UUID5 from question text (enables deduplication)
6. **Real-time Scoring**: Points calculated immediately on answer submission
7. **Lag Analysis**: Track which sub-categories need work via fail_count + days_since

---

## Success Metrics

- ✅ Database schema created
- ✅ Engine class with weighted selection
- ✅ DatabaseClient with full CRUD
- ✅ ~12,100+ GAT questions loaded
- ⏳ Frontend pages (in progress)
- ⏳ Subject questions (blocked on Sanfoundry)
- ⏳ Production deployment (ready once frontend done)
