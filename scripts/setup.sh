#!/usr/bin/env bash
# One-time local setup: venv + Python deps + frontend deps + .env
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-python3}
"$PYTHON" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

(cd frontend && npm install)

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env - add your ANTHROPIC_API_KEY."
fi

cat <<'EOF'

Setup done. Start the app with two shells:
  .venv/bin/uvicorn server:app --reload
  (cd frontend && npm run dev)      # http://localhost:5173
EOF
