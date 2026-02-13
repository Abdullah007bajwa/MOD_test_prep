# PrepMaster AI - Exam Preparation Platform

PrepMaster AI is a comprehensive exam preparation platform featuring weighted learning, mock tests, and targeted practice by category and subcategory. The system prioritizes weak areas through intelligent question selection and provides immediate feedback with explanations.

## Features

### ?? Mock Test Mode
- **100 MCQs** (70% GAT, 30% Subject)
- **120-minute timer** with auto-submit
- **Scoring**: Correct +1.0, Incorrect -0.25, Skip 0.0
- Weighted question selection based on performance history

### ?? Drill Mode (NEW)
- **Practice by Category**: Practice all questions from GAT or Subject category
- **Practice by Subcategory**: Select specific topics to focus on
- **Immediate Feedback**: See correct/incorrect status instantly
- **Explanations**: Detailed explanations shown after each answer
- **Progress Tracking**: Visual progress indicator
- **Low-Count Detection**: Automatically identifies subcategories with <20 questions
- **Online MCQ Discovery**: Find additional sources for low-count subcategories

### ?? Dashboard
- Total question counts by category
- Quick access to start mock tests
- System status overview

## Quick Start

### 1. Setup Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Database

Create a `.env` file in the project root:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

### 3. Initialize Database

Run the SQL schema in your Supabase SQL Editor:

```bash
# See SETUP_DATABASE.md for detailed instructions
# Or run: create_supabase_tables.sql in Supabase dashboard
```

### 4. Load Questions

```bash
# Dry-run (test without uploading)
python importer.py --dry-run
python -m src.indiabix_scraper_v2 --dry-run

# Upload to database (set SUPABASE_URL and SUPABASE_KEY first)
python importer.py
python -m src.indiabix_scraper_v2
```

### 5. Run Application

```bash
streamlit run app.py
```

The app will be available at `http://localhost:8501`

## Project Structure

```
MOD/
??? app.py                      # Main Streamlit application
??? db.py                       # Database functions (Supabase)
??? engine.py                   # Scoring constants
??? importer.py                 # JSONL question importer
??? test_db_counts.py           # Database statistics tool
?
??? src/
?   ??? database.py            # DatabaseClient class
?   ??? engine.py               # TestSession class
?   ??? mcq_discovery.py        # MCQ discovery module (NEW)
?   ??? indiabix_scraper_v2.py  # IndiaBIX scraper
?   ??? pakmcqs_scraper.py      # PakMCQs scraper
?   ??? ...                     # Other scrapers
?
??? database_schema.sql         # PostgreSQL schema
??? create_supabase_tables.sql  # Supabase setup
??? requirements.txt            # Python dependencies
??? README.md                   # This file
```

## Drill Mode Usage

### Selecting a Practice Session

**Option 1: Practice by Category**
1. Navigate to **Drill Mode** in the sidebar
2. Select **Practice Mode**: "By Category"
3. Select **Category** (GAT or Subject)
4. (Optional) Check "Limit number of questions" and set maximum
5. Click **Start Category Practice Session**

**Option 2: Practice by Subcategory**
1. Navigate to **Drill Mode** in the sidebar
2. Select **Practice Mode**: "By Subcategory"
3. Select **Category** (GAT or Subject)
4. Choose a **Subcategory** from the dropdown
   - Question counts are shown for each subcategory
   - ?? Low-count warnings appear for subcategories with <20 questions
5. Click **Start Practice Session**

### During Practice

- **Answer Questions**: Select your answer using radio buttons
- **Submit Answer**: Click "Submit Answer" to see feedback
- **View Explanation**: Explanation appears automatically after submission
- **Navigate**: Use Previous/Next buttons to move between questions
- **Progress**: Track your progress with the progress bar

### Finding More MCQs

For subcategories with fewer than 20 questions:

1. The system automatically shows a **"Find More MCQs Online"** section
2. Browse recommended sources with direct links
3. Expand source cards to see URLs and notes
4. Use the provided search terms to find additional questions

## Database Schema

### Questions Table
- `id` (UUID): Primary key
- `category` (VARCHAR): 'gat' or 'subject'
- `sub_category` (VARCHAR): Topic name (e.g., 'number_series', 'analogies')
- `text` (TEXT): Question text
- `options` (JSONB): Array of answer options
- `correct_answer_idx` (INT): Index of correct answer (0-based)
- `explanation` (TEXT): Explanation text
- `source` (VARCHAR): Source website name

### User Stats Table
- Tracks user performance per question
- `fail_count`, `success_count`, `last_attempted_at`

### Sessions Table
- Tracks mock test sessions
- `score_earned`, `pass_status`, `started_at`, `ended_at`

## API Functions

### Database Functions (`db.py`)

```python
# Get questions by category
get_questions_by_category(category: str, limit: int | None = None)

# Get questions by subcategory (NEW)
get_questions_by_subcategory(category: str, sub_category: str, limit: int | None = None)

# Get subcategory counts (NEW)
get_subcategory_counts(category: str | None = None) -> Dict[str, int]

# Get subcategories for category (NEW)
get_subcategories_by_category(category: str) -> List[str]
```

### MCQ Discovery (`src/mcq_discovery.py`)

```python
# Find low-count subcategories
get_low_count_subcategories(threshold: int = 20, category: str | None = None)

# Get known sources for subcategory
get_sources_for_subcategory(sub_category: str) -> List[Dict]

# Format subcategory name for display
format_subcategory_name(sub_category: str) -> str
```

## Testing

### Test MCQ Discovery Module

```bash
python test_mcq_discovery.py
```

### Check Database Counts

```bash
# All counts
python test_db_counts.py

# Low-count subcategories (<20)
python test_db_counts.py --under 20
```

## Documentation

- **ARCHITECTURE.md**: System architecture and design
- **SETUP_DATABASE.md**: Database setup instructions
- **SCRAPERS_README.md**: Scraper setup and usage
- **SOURCES_TO_ENRICH_DB.md**: Sources for finding more MCQs
- **LOW_COUNT_SUBCATEGORIES.md**: Subcategories needing more questions

## Recent Updates

### Drill Mode Implementation
- ? Category and subcategory filtering
- ? Immediate feedback with correct/incorrect indicators
- ? Explanation display after answering
- ? Low-count subcategory detection
- ? Online MCQ discovery integration
- ? Progress tracking and navigation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

[Add your license here]

## Support

For issues or questions, please open an issue on the repository.
