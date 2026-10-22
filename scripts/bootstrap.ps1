# LCES bootstrap (Windows PowerShell)
# Rebuilds the project-local .venv with Python 3.13 and runs the baseline checks.
# Pass -BrowserQA to also install Playwright + Chromium for Gate 3 browser checks.
param(
    [switch]$BrowserQA
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Local Content Engineering Studio bootstrap =="

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}

uv python install 3.13

if (Test-Path ".venv\pyvenv.cfg") {
    $cfg = Get-Content ".venv\pyvenv.cfg" -Raw
    if ($cfg -notmatch "version_info = 3\.13") {
        Write-Host "-- Existing .venv is not Python 3.13; removing it"
        Remove-Item -Recurse -Force ".venv"
    }
}

if ($BrowserQA) {
    uv sync --extra browser
    Write-Host "-- Installing Chromium for Playwright"
    uv run playwright install chromium
}
else {
    uv sync
}

if (-not (Test-Path ".git")) {
    git init -b main | Out-Null
    Write-Host "-- git repository initialized"
}

uv run lces doctor
uv run pytest
uv run ruff check .

Write-Host ""
Write-Host "Done. Activate later with: .\.venv\Scripts\Activate.ps1"
Write-Host "VS Code interpreter: .\.venv\Scripts\python.exe"
