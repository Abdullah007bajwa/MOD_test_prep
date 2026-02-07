# Create venv, install requirements, run scraping scripts (dry-run by default).
# Usage: .\run_scrapers.ps1          -> dry-run all
#        .\run_scrapers.ps1 -Upsert   -> run with Supabase upsert (requires SUPABASE_URL, SUPABASE_KEY)

param(
    [switch]$Upsert  # If set, run scrapers without --dry-run (upsert to Supabase)
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPath = "venv"
$dryRun = if ($Upsert) { $false } else { $true }

# Create venv if missing
if (-not (Test-Path "$venvPath\Scripts\Activate.ps1")) {
    Write-Host "Creating virtual environment..."
    py -3 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        python -m venv $venvPath
    }
}

# Activate and install requirements
Write-Host "Activating venv and installing requirements..."
& "$venvPath\Scripts\Activate.ps1"
pip install -r requirements.txt --quiet

$dryFlag = if ($dryRun) { "--dry-run" } else { "" }

# Run scrapers
Write-Host "`n--- importer.py (examveda JSONL) ---"
python importer.py $dryFlag

Write-Host "`n--- src.indiabix_scraper_v2 (IndiaBix with pagination) ---"
python -m src.indiabix_scraper_v2 --max-topics 19 --max-questions 50 $dryFlag

Write-Host "`n--- src.pakmcqs_har_scraper (PakMCQs from HAR) ---"
python -m src.pakmcqs_har_scraper $dryFlag

Write-Host "`n--- src.sanfoundry_subject_scraper (Sanfoundry logical-reasoning from HAR) ---"
python -m src.sanfoundry_subject_scraper $dryFlag

Write-Host "`nDone."
if ($dryRun) {
    Write-Host "To upsert to Supabase, set SUPABASE_URL and SUPABASE_KEY and run: .\run_scrapers.ps1 -Upsert"
}
