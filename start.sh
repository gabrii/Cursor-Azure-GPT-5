#!/usr/bin/env bash
# Start the Cursor-Azure-GPT-5 proxy service
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "[cursor-api] Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements/dev.txt -q
fi

PORT="${1:-8082}"
echo "[cursor-api] Starting on http://localhost:$PORT"
echo "[cursor-api] Service API key: $(grep SERVICE_API_KEY .env | cut -d= -f2)"
echo ""
echo "  Cursor settings:"
echo "    OpenAI API Key      → cursor-azure-local"
echo "    Override Base URL   → <your cloudflared tunnel URL>"
echo ""
echo "  Models to add in Cursor:"
echo "    gpt-5.4-none   gpt-5.4-low   gpt-5.4-medium   gpt-5.4-high   gpt-5.4-xhigh"
echo "    gpt-5.4-mini-none   gpt-5.4-mini-low   gpt-5.4-mini-medium   gpt-5.4-mini-high   gpt-5.4-mini-xhigh"
echo ""

FLASK_APP=autoapp.py FLASK_ENV=production .venv/bin/flask run -p "$PORT"
