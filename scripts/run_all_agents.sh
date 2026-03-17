#!/usr/bin/env bash
# run_all_agents.sh — run every agent in agents/ under norma monitoring.
#
# All runs POST telemetry to the norma backend and appear in the dashboard
# in real time via SSE when --remote is used.
#
# Usage:
#   ./scripts/run_all_agents.sh                    # local DB only
#   ./scripts/run_all_agents.sh --remote           # → dashboard real-time (localhost:8080)
#   ./scripts/run_all_agents.sh --repeat 3         # run each agent N times
#   ./scripts/run_all_agents.sh --remote --repeat 3
#   ./scripts/run_all_agents.sh --only financial_reader,research_team
#
# Prerequisites:
#   export OPENAI_API_KEY=sk-...
#   cd backend && poetry install   (first time)
#   norma backend running on :8080 if --remote is used

set -euo pipefail

REMOTE_FLAG=""
REMOTE_URL="http://localhost:8080"
REPEAT=1
ONLY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)  REMOTE_FLAG="--remote-url $REMOTE_URL"; shift ;;
        --repeat)  REPEAT="$2"; shift 2 ;;
        --only)    ONLY="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OPENAI_API_KEY is not set."
    echo "  export OPENAI_API_KEY=sk-..."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
BACKEND_DIR="$PROJECT_ROOT/backend"

# ── Agent definitions ──────────────────────────────────────────────────────────
# Format: "file_path|contract_version|notes"
# Agents marked SKIP need onboarding (no CONTRACT_YAML in module) — run
# `POST /api/agents/onboard` for them first, then remove the SKIP.
# ──────────────────────────────────────────────────────────────────────────────
declare -a AGENT_DEFS=(
    # ── LangChain builders (have CONTRACT_YAML) ────────────────────────────────
    "agents/financial_reader/earnings_report_reader.py|1.0"
    "agents/financial_report_agent/quarterly_report_summarizer.py|1.0"
    "agents/research_pipeline/research_synthesizer.py|1.0"
    "agents/support_triage/ticket_triage.py|1.0"
    "agents/approval_showcase/human_in_loop.py|1.0"

    # ── LangGraph builders (have CONTRACT_YAML) ────────────────────────────────
    "agents/research_team/orchestrator.py|1.0"
    "agents/investment_pipeline/orchestrator.py|1.0"

    # ── LangGraph builders ─────────────────────────────────────────────────────
    "agents/compliance_review/compliance_review_orchestrator.py|1.0"

    # ── LangChain builders ─────────────────────────────────────────────────────
    "agents/market_research/market_research_agent.py|1.0"

    # ── Runner-style agents (manage own session) ───────────────────────────────
    "agents/red_team/attacker.py|1.0"
    "agents/violations_showcase/violations_agent.py|1.0"
    "agents/norma_sentinel/sentinel.py|1.0"

    # ── OpenAI Agents SDK runner ───────────────────────────────────────────────
    "agents/openai_research/oai-research.py|1.0"

    # ── OpenAI function-calling runner ────────────────────────────────────────
    "agents/openai_func/oai-func.py|1.0"

    # ── Standalone HTTP reporter (uses ingest API directly) ────────────────────
    "agents/standalone_otel/standalone_agent.py|1.0"

    # ── Multi-version runs for agents that have v2 contracts ──────────────────
    "agents/financial_reader/earnings_report_reader.py|2.0"
    "agents/financial_report_agent/quarterly_report_summarizer.py|2.0"
)

# ── Filter by --only if specified ─────────────────────────────────────────────
should_run() {
    local file="$1"
    if [[ -z "$ONLY" ]]; then return 0; fi
    IFS=',' read -ra FILTERS <<< "$ONLY"
    for f in "${FILTERS[@]}"; do
        if [[ "$file" == *"$f"* ]]; then return 0; fi
    done
    return 1
}

# ── Banner ─────────────────────────────────────────────────────────────────────
echo ""
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │           norma — run-all-agents script             │"
echo "  └─────────────────────────────────────────────────────┘"
echo ""
echo "  Remote  : ${REMOTE_FLAG:-local DB (norma.db)}"
echo "  Repeat  : $REPEAT"
echo "  Filter  : ${ONLY:-all agents}"
echo ""

PASS=0
FAIL=0
SKIP=0
TOTAL=0

run_agent() {
    local file="$1"
    local contract="$2"
    local run_idx="$3"

    echo "  ── $(basename "$file")  contract=v${contract}  run=${run_idx} ────────────────"

    # shellcheck disable=SC2086
    if (cd "$BACKEND_DIR" && poetry run norma-watch \
        --agent-file "$PROJECT_ROOT/$file" \
        --contract-version "$contract" \
        $REMOTE_FLAG \
        2>&1); then
        PASS=$((PASS + 1))
    else
        echo "  [WARN] exited non-zero for $file v$contract run $run_idx"
        FAIL=$((FAIL + 1))
    fi
    TOTAL=$((TOTAL + 1))
    echo ""
}

# ── Main loop ─────────────────────────────────────────────────────────────────
for def in "${AGENT_DEFS[@]}"; do
    IFS='|' read -r file contract notes <<< "$def"
    notes="${notes:-}"

    if [[ "$notes" == SKIP* ]]; then
        echo "  ── SKIP: $file  (${notes#SKIP:})"
        SKIP=$((SKIP + 1))
        continue
    fi

    if ! should_run "$file"; then
        continue
    fi

    for ((i = 1; i <= REPEAT; i++)); do
        run_agent "$file" "$contract" "$i"
    done
done

# ── Summary ────────────────────────────────────────────────────────────────────
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │  All runs complete                                  │"
printf "  │  Total: %-3d  Passed: %-3d  Failed: %-3d  Skipped: %-3d │\n" \
    "$TOTAL" "$PASS" "$FAIL" "$SKIP"
echo "  └─────────────────────────────────────────────────────┘"
echo ""
echo "  Dashboard → http://localhost:3030"
echo "  API       → http://localhost:8080/api/agents"
echo ""

[[ $FAIL -eq 0 ]]
