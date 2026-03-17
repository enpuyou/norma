# norma.ai — Capability Spec: Agent Onboarding & Discovery
### v1.0, March 2026

---

## Overview

This document specifies the **Agent Onboarding & Discovery** capability for norma.ai — the flow by which a user registers their local AI agents with the platform, generates governance contracts for each, and activates runtime monitoring. This is the entry point into the entire norma.ai system.

The capability is designed for a user who has a directory of LangChain/LangGraph agents on their machine and wants norma to take over governance, monitoring, and tracing with minimal friction.

---

## The Four Sub-Capabilities

1. Agent Discovery (Directory Scan)
2. Contract Auto-Generation
3. Agent Registry & Version Tracking
4. Runtime Instrumentation

---

## Sub-Capability 1 — Agent Discovery

### Trigger
User opens norma.ai and clicks **"Onboard Agents"**. They select or paste a directory path (e.g. `/agents`). Norma scans the directory.

### Behavior

**Step 1: File traversal**
- Recursively walk the directory tree
- Identify all `.py` files
- Skip: `__pycache__`, `.venv`, `node_modules`, `tests/`, `*.test.py`

**Step 2: LangChain/LangGraph pattern detection**
For each `.py` file, scan for presence of:
- LangChain imports: `from langchain`, `from langgraph`, `import langchain`
- Agent constructors: `AgentExecutor`, `create_react_agent`, `StateGraph`, `CompiledGraph`
- Tool definitions: `@tool`, `StructuredTool`, `Tool(`
- LLM instantiation: `ChatOpenAI`, `ChatAnthropic`, `ChatBedrock`, `AzureChatOpenAI`
- Subagent patterns: nested `.invoke(`, `.stream(`, nested `AgentExecutor` instantiation

Files with 2+ matching patterns are flagged as agent files. Files with 1 match are flagged as "possible agent — needs confirmation."

**Step 3: Agent grouping**
Some agents span multiple files (e.g. `agent.py` + `tools.py` + `prompts.py`). Norma groups files that share imports or are imported by a common entry point into a single agent unit.

**Step 4: Extraction**
For each identified agent unit, extract:

| Field | Source |
|---|---|
| `name` | Filename or class name if defined |
| `entry_point` | The file that instantiates the top-level agent |
| `tools` | All tool names found in the file(s) |
| `model` | LLM class and model string (e.g. `gpt-4o`, `claude-sonnet`) |
| `description` | Inferred by Claude from code + docstrings |
| `has_subagents` | Boolean — does it spawn other agents? |
| `file_hash` | SHA256 of all files in the agent unit (for change detection) |
| `discovered_at` | Timestamp |

**Step 5: User confirmation**
Present all discovered agents as a list. For each:
- Show: name, entry point, tools, model, description
- Allow user to: confirm, exclude, rename, or manually group files

User clicks **"Onboard Selected"** to proceed. Excluded agents are not registered.

---

## Sub-Capability 2 — Contract Auto-Generation

### Trigger
After user confirms the agent list, norma generates a contract for each agent — one Claude API call per agent, run in parallel.

### What Claude receives
The full source code of the agent unit (all files in the group), plus a structured prompt instructing it to produce a governance contract in norma's YAML schema.

### Contract schema
```yaml
agent_id: string                  # auto-generated slug from agent name
version: "1.0"
generated_by: norma-auto          # flags this as auto-generated, not human-authored
status: proposed                  # proposed | active | archived
scope:
  description: string             # plain English summary of what this agent does
  allowed_tasks: [string]         # inferred from code behavior
authorities:
  tools:
    allow: [string]               # tools found in code
    deny: [string]                # tools norma recommends blocking (inferred risk)
  data:
    allow: [string]               # data paths/sources accessed
    deny: [string]                # paths norma recommends restricting
output_constraints:
  deny_patterns: [string]         # e.g. pii_regex, credential_regex, ssn_regex
  require: [string]               # required fields in output
sla:
  max_cost_per_run: float         # estimated from model pricing
  max_latency_seconds: int        # conservative default
  min_quality_score: float        # default 0.75
delegation:
  allowed: boolean                # true if subagents detected
  max_subagents: int              # inferred from code
trust:
  initial_score: 0.40             # all new agents start at restricted tier
  tier_thresholds:
    standard:  { min_score: 0.65, min_clean_runs: 10 }
    trusted:   { min_score: 0.82, min_clean_runs: 20 }
notes:
  inferred_from: [string]         # fields inferred confidently from code
  requires_review: [string]       # fields Claude flagged as needing human input
  assumptions: [string]           # explicit list of assumptions made
```

### Human approval gate
Every auto-generated contract has `status: proposed`. It is **never activated automatically**. The user must review and approve before enforcement begins.

The UI presents each contract with:
- A plain-English summary of what the contract permits and restricts
- A clear breakdown of fields inferred confidently vs. assumed
- An inline YAML editor for modifications
- A natural language rule editor: type a sentence (e.g. "this agent should never write to disk"), norma proposes the corresponding YAML clause
- An **"Approve & Activate"** button that sets `status: active`

---

## Sub-Capability 3 — Agent Registry & Version Tracking

### What gets stored
```
agents table:
  agent_id          unique slug
  name              display name
  entry_point       path to main file
  directory         root directory of agent unit
  file_hash         SHA256 of all files at onboard time
  current_version   integer, starts at 1
  current_tier      restricted | standard | trusted
  trust_score       float, starts at 0.40
  status            active | paused | retired
  onboarded_at      timestamp
  last_seen_at      timestamp of most recent run

contracts table:
  agent_id
  version
  yaml_content
  status            proposed | active | archived
  created_by        norma-auto | user
  approved_by       user identifier
  activated_at      timestamp

runs table:
  run_id
  agent_id
  agent_version     (which version of the agent file was running)
  contract_version  (which contract was active during the run)
  started_at / completed_at
  status            success | failure | blocked | timeout
  ... (full telemetry — see Sub-Capability 4)
```

### Change detection
Norma runs a background file watcher on all registered agent directories. When any file in an agent unit changes:

1. Recompute SHA256 hash of the agent unit
2. If hash differs from stored `file_hash`:
   - Increment `current_version` (e.g. v1 → v2)
   - Flag agent in UI: **"Agent code changed — re-analysis recommended"**
   - Offer to re-run contract auto-generation against the new code
   - New contract proposal created with `status: proposed` — existing active contract stays in force until user approves the new one
3. All subsequent runs log against the new `agent_version`, even if the contract has not been updated yet

Every run in the log is traceable to an exact version of both the agent code and the governance contract active at that time.

---

## Sub-Capability 4 — Runtime Instrumentation

### Instrumentation model: CLI wrapper + one-line SDK (hybrid)

**For agents run manually (zero changes to agent file):**
```bash
# Before norma
python agents/research_agent.py

# After norma
norma run agents/research_agent.py
```
Norma injects its callback handler before the agent's code loads by patching LangChain's callback manager at import time via `sitecustomize`.

**For agents run on a schedule (cron, launchd, etc.):**
```python
import norma  # add this one line to the top of the agent file
```
The existing trigger mechanism requires no other changes. Both methods produce identical telemetry.

### What gets captured

**Per LLM call:**
- Model name and version
- Input tokens, output tokens, total tokens
- Estimated cost (based on current model pricing table)
- Latency (ms)
- Input prompt (truncated to 2000 chars for storage)
- Output (truncated to 2000 chars for storage)
- Inference parameters (temperature, etc.)

**Per tool call:**
- Tool name
- Input arguments and output/return value
- Success or failure
- Latency (ms)
- Whether the call was blocked by contract enforcement

**Per run:**
- `run_id` (UUID)
- `agent_id` and `agent_version`
- `contract_version` active at time of run
- Start and end timestamp
- Total cost and total tokens
- Overall status: success | failure | blocked | timeout
- Full execution tree (parent-child step relationships)
- Policy enforcement events: rule triggered, action attempted, outcome (blocked or allowed)

**Subagent detection:**
If the agent spawns subagents (via `AgentExecutor.invoke` or LangGraph node transitions), each subagent run is captured as a child node in the execution tree, linked to the parent `run_id`. The tree records which node spawned which, token and cost contribution per node, and context tokens passed from parent to child (tokens available vs. tokens sent).

### What the user sees

**Run log view:** All runs across all agents, filterable by agent, date, status, cost. Each row shows: agent name, version, contract version, timestamp, status, total cost, total tokens, duration.

**Run detail view:** Clicking a run opens the full execution trace:
- Step-by-step timeline of every LLM call and tool call in order
- Flow visualization showing how context and tokens moved between steps
- If multi-agent: a tree diagram showing parent and child agents with per-node cost and token contribution
- Policy enforcement events highlighted inline
- Summary panel: total cost, total tokens, quality score (if assessed), outcome

**Agent detail view:** Run history for a given agent — run count, success rate, average cost per run, average latency, trust score trajectory, contract version history.

### Policy enforcement at runtime

**Deterministic (always on):**
- Tool access control: calls to tools in `authorities.tools.deny` are intercepted and blocked before execution
- Output pattern matching: output containing patterns in `output_constraints.deny_patterns` is redacted and a violation logged
- Cost limit: if cumulative run cost exceeds `sla.max_cost_per_run`, the run is throttled and alerted
- Latency limit: if `sla.max_latency_seconds` is exceeded, the run is flagged

**Semantic (optional, slower):**
An LLM-powered check evaluates whether agent actions stayed within the contract's stated scope. Configurable per contract. Off by default.

Every enforcement event is logged with: timestamp, run_id, agent_id, rule triggered, action attempted, and outcome.

---

## UI Flow Summary
```
[Onboard Agents]
      │
      ▼
[Select Directory: /agents]
      │
      ▼
[Scanning... found 20 Python files]
[Identified 15 agents, 3 possible matches, 2 excluded (test files)]
      │
      ▼
[Confirmation screen: list of agents with name, tools, model, description]
[User reviews, renames, excludes, confirms]
      │
      ▼
[Generating contracts... 15 Claude API calls, run in parallel]
      │
      ▼
[Fleet view: 15 agent cards]
[Each card: name, tier, status "Contract proposed — needs review"]
      │
      ▼
[User clicks agent card → Agent detail view]
[Description, tools, model, contract YAML]
[Inline editor + natural language rule input]
[Approve & Activate button]
      │
      ▼
[Contract activated — monitoring live]
[Agent runs captured automatically going forward]
      │
      ▼
[Run log populates as agents execute]
[Click any run → execution trace + token flow visualization]
```

---

## Integration with Existing norma.ai Capabilities

| Capability | Dependency on Onboarding |
|---|---|
| Dynamic Authority Calibration | Agent must be registered; trust score initialized at 0.40 |
| Context Budget Routing | Contract must specify `delegation.context_routing` rules; instrumentation must be active |
| Failure Attribution | Requires execution tree logging from instrumentation layer |
| Performance Engine | All metrics computed from run telemetry captured by instrumentation |
| Governance Lifecycle | Contract versioning begins at onboarding; file change detection triggers new proposals automatically |
| Anomaly Alerting | Activates after minimum 20 runs per agent to establish a baseline |

---

## Known Constraints & Boundaries

**What works in MVP:**
- LangChain and LangGraph agents (Python)
- Single-machine, local deployment
- Manual and scheduled agent runs (both covered by hybrid instrumentation)
- Up to ~50 agents per registry instance

**Not in MVP scope:**
- AutoGen, CrewAI, or other frameworks (Phase 2)
- Agents running on remote machines or cloud infrastructure
- Agents not written in Python
- Semantic context relevance scoring (approximated by token overlap in MVP)

**Honest limitations to disclose in demo:**
- Auto-generated contracts are based on static code analysis and may miss runtime behavior not visible in the code
- File hash change detection triggers on any file change, including comments or formatting — not only behavioral changes
- Token cost estimates use a static pricing table and may drift as provider pricing changes
