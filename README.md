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
| Backend | Python 3.11, FastAPI, SQLAlchemy async, Pydantic v2 |
| Agent Runtime | LangChain / LangGraph / OpenAI Agents SDK / CrewAI / AutoGen |
| LLM | OpenAI GPT-4o / GPT-4o-mini (optional; most features work without it) |
| Database | SQLite (dev) → PostgreSQL (prod) — 16 ORM tables |
| Frontend | Next.js 14 (App Router), React 19, TypeScript, Tailwind CSS, Recharts |
| Package management | Poetry (backend), npm (frontend) |
| Testing | pytest — 97 passing tests |

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
poetry run uvicorn norma.main:app --host 0.0.0.0 --port 8080 --reload
# API available at http://localhost:8080
# Swagger docs at  http://localhost:8080/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Dashboard at http://localhost:3030
```

### Seed Demo Data

```bash
cd backend
poetry run python -m norma.seed
# Generates 3 demo workflows with realistic run histories
```

### Run a Real Agent Under Monitoring

```bash
cd backend
export OPENAI_API_KEY=sk-...
poetry run norma-watch --agent-file ../agents/financial_reader/earnings_report_reader.py
```

### Run Tests

```bash
cd backend
poetry run pytest tests/ -v   # 97 passing
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

---

## Project Structure

```
norma/
├── backend/                         # FastAPI application (Python 3.11, Poetry)
│   ├── pyproject.toml
│   ├── norma/
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── config.py                # Settings (pydantic-settings)
│   │   ├── database.py              # SQLAlchemy async engine
│   │   ├── models/                  # ORM models (16 tables)
│   │   ├── schemas/                 # Pydantic request/response schemas
│   │   ├── api/                     # FastAPI routers (40+ endpoints)
│   │   │   ├── agents.py            # Fleet + onboarding
│   │   │   ├── runs.py              # Execution telemetry
│   │   │   ├── contracts.py         # Version lifecycle
│   │   │   ├── compliance.py        # Governance rules
│   │   │   ├── qa.py                # Natural language Q&A
│   │   │   ├── violations.py        # Enforcement audit log
│   │   │   ├── alerts.py            # Dashboard alerts
│   │   │   ├── events.py            # SSE real-time events
│   │   │   ├── analytics.py         # Trends + version checkpoints
│   │   │   └── attributions.py      # Failure root cause
│   │   ├── core/                    # Business logic engines
│   │   │   ├── trust_engine.py      # Trust score + tier transitions
│   │   │   ├── enforcement.py       # 5 pre-execution policy checks
│   │   │   ├── quality_scorer.py    # Quality evaluation (deterministic + LLM)
│   │   │   ├── contract_engine.py   # YAML parsing + validation
│   │   │   ├── contract_generator.py# Auto-generate proposals (never auto-activate)
│   │   │   ├── attribution.py       # Probabilistic failure analysis
│   │   │   ├── enhancement.py       # Workflow improvement recommendations
│   │   │   ├── context_router.py    # Context budget routing
│   │   │   ├── trace.py             # OTel-compatible span collection
│   │   │   ├── anomaly_detector.py  # Statistical anomaly alerts
│   │   │   ├── version_comparator.py# Before/after metric diffs
│   │   │   ├── qa_engine.py         # Conversational Q&A logic
│   │   │   └── compliance/          # Compliance rules (OWASP, NIST, EU AI Act)
│   │   ├── integrations/            # Agent adapters
│   │   │   ├── session_core.py      # Framework-agnostic base class
│   │   │   ├── session.py           # LangChain/LangGraph adapter
│   │   │   ├── openai_agent_adapter.py
│   │   │   ├── openai_func_adapter.py
│   │   │   ├── crewai_adapter.py
│   │   │   ├── autogen_adapter.py
│   │   │   ├── introspect.py        # AST scanner for onboarding
│   │   │   └── watch.py             # norma-watch CLI entry
│   │   ├── agents/                  # Backend agent shims + utilities
│   │   └── seed.py                  # Demo data seeder
│   └── tests/                       # 97 passing tests
├── frontend/                        # Next.js 14 dashboard (React 19, TypeScript)
│   ├── app/
│   │   ├── page.tsx                 # Fleet dashboard (VP/Engineer mode toggle)
│   │   ├── agents/[id]/page.tsx     # Agent detail + contract viewer
│   │   ├── runs/[id]/page.tsx       # Run detail + span tree
│   │   ├── compliance/page.tsx      # Compliance posture
│   │   ├── alerts/page.tsx          # Violation inbox
│   │   └── ...
│   ├── components/
│   │   ├── AgentCard.tsx            # Fleet card
│   │   ├── TrustSparkline.tsx       # Historical trust visualization
│   │   ├── SpanTree.tsx             # Hierarchical trace view
│   │   ├── MetricsTrendCharts.tsx   # Time-series charts with version checkpoints
│   │   ├── PromptInspector.tsx      # LLM message history
│   │   ├── OnboardAgentModal.tsx    # Agent registration (AST → contract)
│   │   ├── GovernanceReports.tsx    # Sentinel sweep results
│   │   └── ...
│   ├── hooks/
│   │   ├── useEventStream.ts        # SSE subscription
│   │   └── useMode.ts               # VP/Engineer mode toggle
│   └── lib/
│       ├── api.ts                   # API client
│       └── types.ts                 # TypeScript types
├── agents/                          # Demo agents
│   ├── financial_reader/            # Financial report summarizer (LangChain)
│   ├── research_team/               # Research pipeline (3-node LangGraph)
│   ├── openai_research/             # OpenAI Agents SDK demo
│   ├── norma_sentinel/              # Governance sweep agent
│   ├── red_team/                    # Security attack simulations
│   └── ... (10+ more agents)
├── data/                            # Demo agent data files
│   ├── public/                      # Public data (allowed by contracts)
│   ├── confidential/                # Confidential data (blocked by enforcement)
│   ├── research/                    # Research papers
│   └── ...
├── docs/
│   ├── WIKI.md                      # Complete technical wiki (1400+ lines)
│   ├── DEMO_PLAN.md                 # Demo preparation guide
│   ├── SYSTEM_DESIGN.md             # Architecture + design decisions
│   ├── FEATURES.md                  # Feature list + status
│   ├── E2E_SCENARIOS_VERIFIED.md    # End-to-end test scenarios
│   ├── design.md                    # Original product design
│   └── ...
├── scripts/
│   └── run_all_agents.sh            # Batch agent runner
├── docker-compose.yml               # Local dev environment
├── .env                             # Local environment (git-ignored)
├── .env.example                     # Example environment
├── .gitignore
└── README.md
```

---

## Key Capabilities

| Capability | Implementation |
| --- | --- |
| **Trust & Tier System** | Score 0.0–1.0, +0.025 per clean run, −0.25 on violation. Restricted → Standard (0.65+, 10 clean) → Trusted (0.82+, 20 clean). Never auto-promotes. |
| **Enforcement Engine** | 5 deterministic pre-execution checks: tool ACL, data path glob, output PII patterns, cost SLA, latency SLA. Always runs, cannot be bypassed. |
| **Quality Scoring** | Deterministic checks (output length, error keywords, format, PII) + optional GPT-4o-mini judge. Composite 40% deterministic + 60% LLM. |
| **Contract Lifecycle** | YAML policies, versioned, human-reviewed before activation. Full audit trail (who changed what, when, why). |
| **Multi-Agent Orchestration** | Run tree (parent-child), sub-agent spans, context routing, attribution (probabilistic failure analysis). |
| **Compliance Posture** | 12 rules: OWASP LLM Top 10 (5), NIST AI RMF (3), EU AI Act (3), model drift (1). Pass/fail per rule with evidence. PDF export. |
| **Observability** | OTel-compatible spans (trace trees), SSE real-time events, span waterfall timeline, LLM message history. |
| **Enhancement Recommendations** | 3 types: token waste, violation patterns, cost hotspots. Includes confidence levels + YAML fix suggestions. |

## Demo Agents

All 15+ agents are real and runnable:

| Agent | Framework | Purpose | Demo Value |
| --- | --- | --- | --- |
| **Financial Reader** | LangChain ReAct | Read + summarize public earnings reports | Shows enforcement (confidential blocked), contract v1→v2 upgrade |
| **Research Orchestrator** | LangGraph (3 nodes) | Fetch papers → analyze → write report | Multi-agent spans, sub-agent delegation, attribution |
| **OpenAI Research** | OpenAI Agents SDK | Research synthesis | Framework adapter demonstration |
| **Norma Sentinel** | LangGraph | Fleet governance sweep | Anomaly detection, governance reporting |
| **Red Team** | LangChain | Intentional violations | Security testing, policy enforcement showcase |
| **Investment Pipeline** | LangGraph | NVDA analysis + risk report | Complex workflows, cost analysis |
| **Support Triage** | Multi-turn | Customer ticket routing | Session grouping, escalation |

---

## Documentation

- **[WIKI.md](docs/WIKI.md)** — Complete technical reference (1400+ lines). Everything you need to answer any question during a presentation.
- **[DEMO_PLAN.md](docs/DEMO_PLAN.md)** — Demo preparation guide with step-by-step instructions.
- **[SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)** — Architecture overview and design decisions.
- **[FEATURES.md](docs/FEATURES.md)** — Feature checklist with implementation status.
- **[E2E_SCENARIOS_VERIFIED.md](docs/E2E_SCENARIOS_VERIFIED.md)** — End-to-end test scenarios and verification.

---

## Status

**What's Implemented & Tested:**

- ✅ Trust engine (score math, tier transitions)
- ✅ Enforcement (all 5 checks, always runs, cannot bypass)
- ✅ Quality scoring (deterministic + LLM judge)
- ✅ Contract YAML parsing, versioning, human approval
- ✅ Compliance rules (OWASP, NIST, EU AI Act)
- ✅ Attribution engine (probabilistic multi-node analysis)
- ✅ Enhancement recommendations (3 types)
- ✅ Context routing (token budget enforcement)
- ✅ OTel-compatible span system
- ✅ All API endpoints (40+ routes)
- ✅ Dashboard (fleet, agent detail, run detail, compliance, alerts)
- ✅ SSE real-time events
- ✅ norma-watch CLI
- ✅ Agent onboarding (AST scan → contract proposal)
- ✅ Multi-agent orchestration (run tree, sub-agent spans)
- ✅ 97 passing tests

**Not Yet Implemented:**

- Semantic enforcement (LLM-based policy checks — flag exists)
- OTLP export to external collectors (flag exists)
- API key authentication (flag exists)
- Outbound webhooks (Slack, email, PagerDuty)
- WebSocket streaming (using SSE + polling instead)
