#!/usr/bin/env bash
# One-shot bootstrap for advisory-agent on Linux/Ubuntu.
#
# Idempotent. Creates .venv, installs requirements, copies .env.example -> .env,
# starts the Postgres container, and runs db migrations.
#
# Usage:
#   ./setup.sh
#   source .venv/bin/activate   # then activate the venv in your shell
#
# Note: on a stock Ubuntu the `python3.12-venv` package may be missing, so a
# fresh venv has no pip. This script detects that and bootstraps pip via
# get-pip.py (no sudo needed). For a cleaner install you may instead run:
#   sudo apt-get install -y python3.12-venv python3-pip

set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\033[0;36m==> %s\033[0m\n' "$1"; }

# Pick a Python 3.12 interpreter (fall back to python3).
PY="$(command -v python3.12 || command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "ERROR: python3 not found on PATH" >&2
    exit 1
fi

VENV_PY=".venv/bin/python"

# 1. Python venv
if [ ! -x "$VENV_PY" ]; then
    step "Creating .venv ($("$PY" --version 2>&1))"
    # --without-pip is harmless when ensurepip exists; required when it doesn't.
    "$PY" -m venv .venv --without-pip
else
    step ".venv already exists — skipping create"
fi

# 2. Ensure pip exists inside the venv (bootstrap if Ubuntu shipped no ensurepip)
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    step "Bootstrapping pip into .venv"
    if "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1; then
        :
    else
        GETPIP="$(mktemp /tmp/get-pip-XXXXXX.py)"
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GETPIP"
        elif command -v wget >/dev/null 2>&1; then
            wget -qO "$GETPIP" https://bootstrap.pypa.io/get-pip.py
        else
            echo "ERROR: need curl or wget to bootstrap pip" >&2
            exit 1
        fi
        "$VENV_PY" "$GETPIP"
        rm -f "$GETPIP"
    fi
fi

# 3. Dependencies
step "Installing requirements.txt"
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r requirements.txt

# 4. .env
if [ ! -f .env ]; then
    step "Copying .env.example -> .env"
    cp .env.example .env
    echo "    (edit .env and set GEMINI_API_KEY before running anything that calls Gemini)"
else
    step ".env already exists — skipping copy"
fi

# 5. Docker DB
if command -v docker >/dev/null 2>&1; then
    step "Starting Postgres via docker compose"
    docker compose up -d --wait db
else
    step "docker not found — SKIPPING database (install Docker to run the app / integration tests)"
fi

# 6. Migrations + source registry seed (only if the DB is reachable)
if command -v docker >/dev/null 2>&1; then
    step "Applying migrations (python -m db.setup_db)"
    "$VENV_PY" -m db.setup_db
fi

echo ""
printf '\033[0;32mSetup complete.\033[0m\n'
echo "Next steps:"
echo "  source .venv/bin/activate"
echo "  set -a; . ./.env; set +a            # load .env into the shell"
echo "  pytest -m \"not integration\"          # unit suite (no DB / no Gemini key needed)"
echo "  uvicorn web.app:build_app --factory --reload --host 127.0.0.1 --port 8000"
