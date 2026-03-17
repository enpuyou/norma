# norma.ai

> **The Operating System for Your AI Agents.**
> norma.ai tells you what your AI agents are allowed to do, whether they're doing it well, and how every change impacts performance — in one place, continuously, with evidence.

---

## What It Does

| Capability | Description |
|---|---|
| **Agent Contracts** | Human-readable, machine-enforceable YAML policies — versioned, reviewed, and enforced at runtime |
| **Contract Auto-Generation** | Drop in an agent config; get a YAML draft reviewed by a human before it activates |
| **Runtime Enforcement** | Deterministic tool/data/output enforcement at execution time, not logged after the fact |
| **Performance Engine** | Quality score, cost per task, quality-adjusted cost — with confidence intervals, not point estimates |
| **Dynamic Authority Calibration** | Trust score rises with clean runs, contracts automatically. Violations auto-demote. Human approves expansions. |
| **Context Budget Routing** | Parent agents route only relevant context to each subagent — reducing cost without degrading quality |
| **Failure Attribution** | Probabilistic per-node attribution in multi-agent pipelines. Rates confidence. Does not blame agents for bad inputs. |
| **Governance Lifecycle** | Full contract version history, change diffs, anomaly alerts, one-click compliance export |

---

## Architecture

```
Dashboard (Next.js)  ←→  FastAPI Backend  ←→  LangGraph Middleware
                              ↓
                       SQLite / Postgres
                       (9-table schema)
```

**Two audiences, one product:**
- **VP / Manager mode** — cost per task, quality trends, plain-English alerts, one-click audit export
- **Engineer mode** — execution trees, contract diffs, trust score curves, raw enforcement logs

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy |
| Agent Runtime | LangChain / LangGraph |
| LLM | OpenAI (gpt-4o) |
| Database | SQLite (dev) → PostgreSQL (prod) |
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| Package management | Poetry (backend), npm (frontend) |
| Testing | pytest |

---

## Quick Start

### Prerequisites

- Python 3.12
- [Poetry](https://python-poetry.org/docs/#installation)
- Node.js 20+
- An OpenAI API key

### Backend

```bash
cd backend
poetry install
cp ../.env.example ../.env     # fill in OPENAI_API_KEY
poetry run uvicorn norma.main:app --reload
# API available at http://localhost:8000
# Docs at        http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
cp ../.env.example .env.local  # set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
# Dashboard at http://localhost:3000
```

### Run Tests

```bash
cd backend
poetry run pytest tests/ -v
```

### OTLP Trace Export (Jaeger / Grafana / Datadog)

norma can export run span trees to any OTLP/HTTP trace collector.

Set these environment variables in `.env`:

```bash
ENABLE_OTLP_EXPORT=true
OTLP_ENDPOINT=http://localhost:4318/v1/traces
OTLP_SERVICE_NAME=norma-ai
# optional JSON string for auth headers
OTLP_HEADERS_JSON={"Authorization":"Bearer <token>"}
```

Common endpoints:

- Jaeger OTLP/HTTP: `http://localhost:4318/v1/traces`
- Grafana Alloy / Tempo OTLP/HTTP: `http://localhost:4318/v1/traces`
- Datadog OTLP ingest: `https://otlp-http-intake.logs.datadoghq.com/v1/traces`

Notes:

- Export is non-blocking for runs: persistence succeeds even if export fails.
- Headers are passed via `OTLP_HEADERS_JSON` as a JSON object string.
- Export payload includes tokens, cost, latency, framework, contract version, and span I/O previews.

### Seed Demo Data

```bash
cd backend
poetry run python -m norma.seed
# Seeds all three demo workflows with realistic run histories
```

---

## Project Structure

```
norma/
├── backend/                         # FastAPI application (Poetry)
│   ├── pyproject.toml
│   ├── norma/
│   │   ├── main.py                  # App entry point
│   │   ├── config.py                # Settings (pydantic-settings)
│   │   ├── database.py              # SQLAlchemy engine + session
│   │   ├── models/                  # ORM models (9 tables)
│   │   ├── schemas/                 # Pydantic request/response schemas
│   │   ├── api/                     # FastAPI routers
│   │   ├── core/                    # Business logic
│   │   │   ├── contract_engine.py   # Contract parsing + validation
│   │   │   ├── enforcement.py       # Runtime enforcement middleware
│   │   │   ├── trust_engine.py      # Trust score + tier transitions
│   │   │   ├── attribution.py       # Failure attribution engine
│   │   │   ├── context_router.py    # Context budget routing
│   │   │   ├── contract_generator.py# LLM-powered auto-gen
│   │   │   ├── anomaly_detector.py  # Statistical anomaly alerts
│   │   │   ├── version_comparator.py# Before/after metric diffs
│   │   │   └── qa_engine.py         # Conversational Q&A (data-grounded)
│   │   ├── middleware/              # LangGraph hooks + execution logger
│   │   ├── workflows/               # Three demo workflows
│   │   └── seed.py                  # Demo data seeder
│   └── tests/
│       ├── test_workflow_1_dynamic_authority.py
│       ├── test_workflow_2_context_routing.py
│       └── test_workflow_3_failure_attribution.py
├── frontend/                        # Next.js dashboard
│   ├── app/
│   │   ├── page.tsx                 # Fleet view (VP / Engineer toggle)
│   │   ├── agents/[id]/             # Agent detail page
│   │   └── ...
│   └── components/
├── docs/
│   └── design.md                    # Full product design document
├── .env.example
├── .gitignore
├── TASKS.md                         # Detailed build roadmap
└── README.md
```

---

## The Three Demo Workflows

All tests run against live system state — there is no separate demo mode.

| Workflow | Agent | Primary Capability Tested |
|---|---|---|
| **WF1** | Financial Report Agent | Dynamic Authority Calibration |
| **WF2** | Research Report Pipeline | Context Budget Routing |
| **WF3** | Customer Support Triage | Failure Attribution |

Each workflow has a full pytest suite with `assert` statements. See [`TASKS.md`](TASKS.md) for test details.

---

## Design Principles

1. **Evidence over confidence** — no claim without a data source, sample size, and window
2. **Proposals, not verdicts** — LLM output is always a starting point, never an auto-deployed policy
3. **Two audiences, one data layer** — VP and Engineer modes read from the same DB
4. **Honest AI tooling** — uncertainty is surfaced, not hidden

Full design doc: [docs/design.md](docs/design.md)

---

## Build Roadmap Summary

| Phase | Focus | Est. |
|---|---|---|
| 1 | Contract schema, version store, auto-generator | 3–4 hrs |
| 2 | LangGraph middleware: enforcement + execution logger | 4–5 hrs |
| 3 | WF1 — Financial Report Agent + Trust Engine | 3–4 hrs |
| 4 | WF2 — Research Pipeline + Context Routing | 4–5 hrs |
| 5 | WF3 — Support Triage + Attribution Engine | 4–5 hrs |
| 6 | Dashboard — VP mode + Engineer mode | 4–5 hrs |
| 7 | Conversational Q&A + Recommendations + Compliance Export | 3–4 hrs |
| 8 | Demo polish, seed data, final test run | 3–4 hrs |

See [`TASKS.md`](TASKS.md) for task-level breakdown.
