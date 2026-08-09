# Devin BDR Agent

LangGraph BDR agent (lead discovery → dedupe → research → scoring → human gate → email/phone
enrichment → drafting → Slack/email notify) behind a FastAPI backend and a React/Vite UI with
Chat, Leads Database, Usage & Spend and Settings tabs.

Architecture and node-by-node walkthrough: [`01-how-it-works (1).md`](./01-how-it-works%20\(1\).md),
designs and plans in [`docs/superpowers/`](./docs/superpowers).

## Prerequisites

- Python 3.10+ (3.12 recommended)
- Node.js 22+ (20 works, but `npm install` warns about `@testing-library/jest-dom`)
- An Anthropic API key (contact enrichment runs on Claude's web search + web fetch tools)

## Setup

```bash
git clone https://github.com/SamRobinson123/Devin_BDR_Agent.git
cd Devin_BDR_Agent
bash scripts/setup.sh          # Windows: powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

The script creates `.venv`, installs Python + frontend deps, and copies `.env.example` to `.env`.
Then put your keys in `.env` (see `.env.example` for every supported variable):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Manual equivalent:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd frontend && npm install)
cp .env.example .env
```

## Run

Two processes, from the repo root:

```bash
.venv/bin/uvicorn server:app --reload      # API on http://localhost:8000
(cd frontend && npm run dev)               # UI on http://localhost:5173
```

On Windows use `.venv\Scripts\uvicorn server:app --reload`.

Open http://localhost:5173. `leads.db` and `agent.db` are created on first start; both are
gitignored, so a fresh clone starts with an empty database.

If the backend has to run on another port, point the UI at it with
`frontend/.env` (`VITE_API_BASE_URL=http://localhost:8001`) and add that origin to the CORS
`allow_origins` list in `server.py` if you also move the UI.

## Which keys do what

| Variable | Needed for | Without it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | every node, incl. contact enrichment (web search + web fetch) | app boots, UI works, agent runs fail |
| `ANTHROPIC_MODEL`, `ANTHROPIC_SEARCH_MODEL`, `LEADS_DB_PATH`, `AGENT_DB_PATH` | overrides | defaults are used |

Slack webhook, SMTP credentials and the Anthropic admin key (billed spend) are entered in the UI
Settings / Usage tabs and stored in the `settings` table — not in `.env`.

## Tests and lint

```bash
.venv/bin/python -m pytest -q
(cd frontend && npm test && npm run lint)
```

The Python suite runs with no API keys set.
