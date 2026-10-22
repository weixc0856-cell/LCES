# LCES milestone check (Windows PowerShell)
# Runs the environment / local-model / baseline checks and writes a redacted report.
# Usage:  .\scripts\milestone-check.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$report = Join-Path $root "var\milestone-report.txt"
New-Item -ItemType Directory -Force (Split-Path $report) | Out-Null
Set-Content -Path $report -Value "LCES milestone check $(Get-Date -Format o)" -Encoding utf8

$failures = New-Object System.Collections.Generic.List[string]

function Write-Section([string]$title) {
    Write-Host ""
    Write-Host "== $title ==" -ForegroundColor Cyan
    Add-Content -Path $report -Value "`n== $title ==" -Encoding utf8
}

function Run-Cmd([string]$exe, [string[]]$arguments) {
    $output = & $exe @arguments 2>&1
    $code = $LASTEXITCODE
    if ($null -ne $output) {
        $output | ForEach-Object { Write-Host $_ }
        $output | Out-File -FilePath $report -Append -Encoding utf8
    }
    return $code
}

function Invoke-Check([string]$title, [scriptblock]$block) {
    Write-Section $title
    try {
        & $block
    }
    catch {
        [void]$failures.Add($title)
        Write-Host "FAILED: $title - $_" -ForegroundColor Red
        Add-Content -Path $report -Value "FAILED: $title - $_" -Encoding utf8
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
}

Invoke-Check "git repository" {
    if ((Run-Cmd "git" @("status", "--short")) -ne 0) { throw "git status failed" }
    Run-Cmd "git" @("branch", "--show-current") | Out-Null
    Run-Cmd "git" @("log", "-1", "--oneline") | Out-Null
    Run-Cmd "git" @("remote", "-v") | Out-Null
    if ((Run-Cmd "git" @("status", "--porcelain")) -ne 0) { throw "git status --porcelain failed" }
}

Invoke-Check "python environment" {
    $cfg = Join-Path $root ".venv\pyvenv.cfg"
    if (-not (Test-Path $cfg)) {
        throw "missing .venv; run .\scripts\bootstrap.ps1 first"
    }
    Get-Content $cfg | Select-String "version_info" | ForEach-Object {
        Write-Host $_
        Add-Content -Path $report -Value $_ -Encoding utf8
    }
    if ((Run-Cmd "uv" @("run", "python", "--version")) -ne 0) { throw "uv run python failed" }
    $version = (& uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0 -or $null -eq $version) { throw "could not read Python version" }
    if ($version.Trim() -ne "3.13") {
        throw "expected Python 3.13, got $version; run .\scripts\bootstrap.ps1"
    }
}

Invoke-Check "lces doctor" {
    if ((Run-Cmd "uv" @("run", "lces", "doctor")) -ne 0) { throw "doctor failed" }
}

Invoke-Check "pytest" {
    if ((Run-Cmd "uv" @("run", "pytest", "-q")) -ne 0) { throw "pytest failed" }
}

Invoke-Check "ruff check" {
    if ((Run-Cmd "uv" @("run", "ruff", "check", ".")) -ne 0) { throw "ruff check failed" }
}

Invoke-Check "ruff format --check" {
    if ((Run-Cmd "uv" @("run", "ruff", "format", "--check", ".")) -ne 0) {
        throw "format check failed"
    }
}

Invoke-Check "mypy" {
    if ((Run-Cmd "uv" @("run", "mypy", "src")) -ne 0) { throw "mypy failed" }
}

$previousProvider = $env:LCES_PROVIDER
$env:LCES_PROVIDER = "local"
try {
    Invoke-Check "local model probe" {
        if ((Run-Cmd "uv" @("run", "lces", "models", "--provider", "local")) -ne 0) {
            throw "local model probe failed"
        }
    }

    Invoke-Check "local model generation (lces models --test)" {
        if ((Run-Cmd "uv" @("run", "lces", "models", "--provider", "local", "--test")) -ne 0) {
            throw "local generation failed"
        }
    }
}
finally {
    $env:LCES_PROVIDER = $previousProvider
}

# Redact secrets before the report is shared.
$content = Get-Content -Path $report -Raw
$content = [regex]::Replace($content, 'sk-[A-Za-z0-9_-]{16,}', 'sk-***')
$content = [regex]::Replace($content, '(?im)^(LCES_[A-Z0-9_]*KEY\s*=).*$', '$1***')
$content = [regex]::Replace($content, '(?i)(api[_-]?key\s*[:=]\s*)\S+', '$1***')
$content = [regex]::Replace($content, '(?i)(authorization:\s*bearer\s*)\S+', '$1***')
Set-Content -Path $report -Value $content -Encoding utf8

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host ("FAILED checks: " + ($failures -join ", ")) -ForegroundColor Red
    Write-Host "Report: $report"
    exit 1
}

Write-Host "All milestone checks passed." -ForegroundColor Green
Write-Host "Report: $report"
exit 0
