#requires -Version 5.1
<#
.SYNOPSIS
    One-shot bootstrap for advisory-agent on Windows.

.DESCRIPTION
    Idempotent. Creates .venv, installs requirements, copies .env.example -> .env,
    starts the Postgres container, and runs db migrations.

.EXAMPLE
    .\setup.ps1
    .\.venv\Scripts\Activate.ps1   # then activate the venv in your shell
#>

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# 1. Python venv
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    Write-Step 'Creating .venv (Python 3.12)'
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3.12 -m venv .venv } else { & python -m venv .venv }
} else {
    Write-Step '.venv already exists — skipping create'
}

$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

# 2. Dependencies
Write-Step 'Installing requirements.txt'
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt

# 3. .env
if (-not (Test-Path .\.env)) {
    Write-Step 'Copying .env.example -> .env'
    Copy-Item .env.example .env
} else {
    Write-Step '.env already exists — skipping copy'
}

# 4. Docker DB
Write-Step 'Starting Postgres via docker compose'
& docker compose up -d --wait db
if ($LASTEXITCODE -ne 0) { throw 'docker compose failed — is Docker Desktop running?' }

# 5. Migrations + source registry seed
Write-Step 'Applying migrations (python -m db.setup_db)'
& $venvPy -m db.setup_db

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host 'Next steps:'
Write-Host '  .\.venv\Scripts\Activate.ps1'
Write-Host '  # load .env into the shell (see QUICKSTART.md step 3)'
Write-Host '  pytest -m "not integration"'
Write-Host '  uvicorn web.app:build_app --factory --reload'
