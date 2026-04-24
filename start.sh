#!/usr/bin/env bash
# Start the local Cursor Azure proxy service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "[cursor-api] Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements/dev.txt -q
fi

PORT="${1:-8082}"
SERVICE_KEY="${SERVICE_API_KEY:-}"

if [ -z "${SERVICE_KEY}" ] && [ -f ".env" ]; then
    SERVICE_KEY="$(grep '^SERVICE_API_KEY=' ".env" | cut -d= -f2- || true)"
fi

SERVICE_KEY="${SERVICE_KEY:-change-me}"

echo "[cursor-api] Starting on http://localhost:$PORT"
echo "[cursor-api] Service API key: ${SERVICE_KEY}"
echo ""
echo "  Cursor settings:"
echo "    OpenAI API Key    -> ${SERVICE_KEY}"
echo "    Override Base URL -> <your cloudflared tunnel URL>"
echo ""
echo "  Supported model ids to add in Cursor:"
echo "    gpt-5"
echo "    gpt-5-mini"
echo "    gpt-5-codex"
echo "    gpt-5.1"
echo "    gpt-5.1-codex"
echo "    gpt-5.1-codex-max"
echo "    gpt-5.1-codex-mini"
echo "    gpt-5.2"
echo "    gpt-5.2-codex"
echo "    gpt-5.3-codex"
echo "    gpt-5.4"
echo "    gpt-5.4-mini"
echo "    gpt-5.4-nano"
echo ""
echo "  Optional deployment mapping:"
echo '    AZURE_MODEL_DEPLOYMENTS='\''{"gpt-5.4":"my-prod-gpt54","gpt-5.4-mini":"team-mini"}'\'''
echo ""

FLASK_APP=autoapp.py FLASK_ENV=production .venv/bin/flask run -p "$PORT"
