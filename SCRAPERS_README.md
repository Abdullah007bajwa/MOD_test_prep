# Scrapers setup and run

## 1. Create virtual environment and install requirements

From the project root (`e:\MOD`):

```powershell
# PowerShell
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Or with cmd:

```cmd
py -3 -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
```

If `py` is not available, use `python` (ensure Python 3.11+ is installed and on PATH).

## 2. Run scraping scripts

**Dry-run (parse only, no Supabase):**

```powershell
.\venv\Scripts\Activate.ps1
python importer.py --dry-run
python -m src.har_scraper --dry-run
python -m src.pakmcqs_scraper --dry-run
python -m src.sanfoundry_scraper --dry-run
python -m src.sanfoundry_subject_scraper --dry-run
```

Or use the helper script:

```powershell
.\run_scrapers.ps1
```

```cmd
run_scrapers.bat
```

**Upsert to Supabase:** Set `SUPABASE_URL` and `SUPABASE_KEY`, then run without `--dry-run`:

```powershell
$env:SUPABASE_URL = "your-url"
$env:SUPABASE_KEY = "your-key"
.\run_scrapers.ps1 -Upsert
```

Or run each script manually without `--dry-run`.

## Scripts

| Script | Source | Default input |
|--------|--------|----------------|
| `importer.py` | examveda JSONL | `examveda_all_topics_20260110_181441.jsonl` |
| `src.har_scraper` | IndiaBix HAR | `www.indiabix.com.har` |
| `src.pakmcqs_scraper` | pakmcqs HAR | `pakmcqs.com.har` |
| `src.sanfoundry_scraper` | Sanfoundry logical-reasoning (GAT) | `www.sanfoundry.com.har` |
| `src.sanfoundry_subject_scraper` | Sanfoundry subject (30%: DS, OOPS, OS, networking, OpenCV, etc.) | `www.sanfoundry.com.har` |
