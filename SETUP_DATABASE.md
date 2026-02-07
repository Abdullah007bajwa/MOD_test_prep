# Database Setup Instructions

## Step 1: Create Supabase Tables

1. Go to your Supabase project: https://app.supabase.com
2. Navigate to **SQL Editor** (left sidebar)
3. Click **New Query**
4. Copy the contents of `create_supabase_tables.sql`
5. Paste into the SQL editor
6. Click **Run** (or press Ctrl+Enter)
7. Verify success: Should see "Success. No rows returned"

## Step 2: Verify Table Creation

Run this query in SQL Editor:
```sql
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name IN ('questions', 'user_stats', 'sessions', 'session_answers');
```

Should return 4 rows.

## Step 3: Test Connection from Python

```bash
python -c "from db import get_supabase_uncached; client = get_supabase_uncached(); print(client.table('questions').select('id').limit(1).execute())"
```

Should return: `data=[] count=None`

## Step 4: Run Full IndiaBIX Extraction with Backup

```bash
python -m src.indiabix_scraper_v2 --max-topics 19 --max-questions 1000 --backup-json
```

This will:
- Extract ~874 questions from all 19 IndiaBIX topics
- Save backup to `data/indiabix_backup_YYYYMMDD_HHMMSS.json`
- Upsert to Supabase `questions` table

## Step 5: Verify Data in Supabase

```sql
SELECT 
    source,
    category,
    COUNT(*) as count
FROM questions
GROUP BY source, category
ORDER BY source, category;
```

Expected: ~874 rows with `source='indiabix'` and `category='gat'`

## Troubleshooting

**Error: "Could not find the table 'public.questions' in the schema cache"**
- Solution: Run `create_supabase_tables.sql` in Supabase SQL Editor

**Error: "duplicate key value violates unique constraint"**
- Solution: Questions already exist, this is expected (upsert will update them)

**Backup file not created**
- Check: `--backup-json` flag is present
- Check: `data/` directory created (scraper creates automatically)

## File Locations

- SQL Schema: `create_supabase_tables.sql`
- Python Scraper: `src/indiabix_scraper_v2.py`
- Backup Directory: `data/` (auto-created)
- Environment: `.env` (SUPABASE_URL, SUPABASE_KEY)
