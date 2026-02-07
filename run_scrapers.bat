@echo off
REM Create venv, install requirements, run scraping scripts (dry-run).
REM Requires: py launcher or python on PATH. For upsert: set SUPABASE_URL and SUPABASE_KEY.

cd /d "%~dp0"

set PY=py
where py >nul 2>nul || set PY=python

if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    %PY% -3 -m venv venv 2>nul || %PY% -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt -q

echo.
echo --- importer.py (examveda JSONL) ---
python importer.py --dry-run

echo.
echo --- src.har_scraper (IndiaBix HAR) ---
python -m src.har_scraper --dry-run

echo.
echo --- src.pakmcqs_scraper (pakmcqs HAR) ---
python -m src.pakmcqs_scraper --dry-run

echo.
echo --- src.sanfoundry_scraper (Sanfoundry logical-reasoning HAR) ---
python -m src.sanfoundry_scraper --dry-run

echo.
echo --- src.sanfoundry_subject_scraper (Sanfoundry subject HAR) ---
python -m src.sanfoundry_subject_scraper --dry-run

echo.
echo --- src.gotest_live_scraper (gotest.com.pk GAT) ---
python -m src.gotest_live_scraper --dry-run

echo.
echo Done. To upsert: set SUPABASE_URL and SUPABASE_KEY, then run scrapers without --dry-run.
