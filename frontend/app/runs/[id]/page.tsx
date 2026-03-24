"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ModeToggle } from "@/components/ModeToggle";
import { SpanTree } from "@/components/SpanTree";
import { WaterfallTimeline } from "@/components/WaterfallTimeline";
import { PromptInspector } from "@/components/PromptInspector";
import { getRun, getRunMetrics, getRunSpans, getRunTree, getRunPrompts, type RunMetrics, type RunRecord, type RunSpansResponse, type PromptSnapshot } from "@/lib/api";
import type { RunTreeNode } from "@/lib/types";

// ─── Quality breakdown panel ───────────────────────────────────────────────────
const CHECK_LABELS: Record<string, string> = {
  output_length: "Output Length",
  error_keywords: "No Error Keywords",
  format_compliance: "Format Compliance",
  contract_scope: "Contract Scope",
  blocked: "Execution Blocked",
};

function QualityBreakdownPanel({
  score,
  rationale,
  breakdown,
}: {
  score: number | null;
  rationale: string | null;
  breakdown: Record<string, number> | null;
}) {
  if (score === null && !rationale && !breakdown) return null;

  const pct = score !== null ? Math.round(score * 100) : null;
  const scoreColor = pct !== null ? (pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--amber)" : "var(--red)") : "var(--text-dim)";

  return (
    <div style={{
      background: "var(--bg-2)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      padding: "16px 20px",
      display: "flex",
      flexDirection: "column",
      gap: 14,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
          Quality Evaluation
        </span>
        {pct !== null && (
          <span style={{ fontSize: "22px", fontWeight: 700, fontFamily: "var(--font-mono)", color: scoreColor }}>
            {pct}%
          </span>
        )}
      </div>

      {/* Per-check breakdown bars */}
      {breakdown && Object.keys(breakdown).length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {Object.entries(breakdown).map(([key, val]) => {
            if (key === "blocked") return null;
            const checkPct = typeof val === "number" ? Math.round(val * 100) : 0;
            const checkColor = checkPct >= 80 ? "var(--green)" : checkPct >= 50 ? "var(--amber)" : "var(--red)";
            return (
              <div key={key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", minWidth: 140 }}>
                  {CHECK_LABELS[key] ?? key}
                </span>
                <div style={{ flex: 1, height: 5, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${checkPct}%`, height: "100%", background: checkColor, transition: "width 0.4s ease" }} />
                </div>
                <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: checkColor, minWidth: 32, textAlign: "right" }}>
                  {checkPct}%
                </span>
              </div>
            );
          })}
          {breakdown.blocked && (
            <div style={{ padding: "5px 10px", background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-sm)", fontSize: "10px", color: "var(--red)", fontFamily: "var(--font-mono)" }}>
              Run was blocked — quality score forced to 0
            </div>
          )}
        </div>
      )}

      {/* LLM rationale */}
      {rationale && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
            LLM Evaluator Rationale
          </span>
          <div style={{
            padding: "10px 14px",
            background: "var(--bg-1)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            fontSize: "12px",
            color: "var(--text-secondary)",
            lineHeight: 1.6,
            fontFamily: "var(--font-sans, var(--font-mono))",
            whiteSpace: "pre-wrap",
          }}>
            {rationale}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Status helpers ────────────────────────────────────────────────────────────
const STATUS_COLOR: Record<string, string> = {
  success: "var(--green)",
  failed: "var(--red)",
  timeout: "var(--amber)",
  escalated: "var(--blue)",
};

function statusDot(status: string) {
  return (
    <span style={{
      display: "inline-block",
      width: 6,
      height: 6,
      borderRadius: "50%",
      background: STATUS_COLOR[status] ?? "var(--text-dim)",
      marginRight: 6,
    }} />
  );
}

function qualityBar(score: number | null) {
  if (score === null) return <span style={{ color: "var(--text-dim)" }}>—</span>;
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--amber)" : "var(--red)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 48, height: 4, background: "var(--bg-4)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color }} />
      </div>
      <span style={{ color, fontFamily: "var(--font-mono)", fontSize: "11px" }}>{pct}%</span>
    </div>
  );
}

// ─── Tree node component ───────────────────────────────────────────────────────
function RunNode({
  node,
  depth = 0,
  isLast = true,
}: {
  node: RunTreeNode;
  depth?: number;
  isLast?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  const hasViolations = node.violations.length > 0;
  const statusColor = STATUS_COLOR[node.completion_status] ?? "var(--text-dim)";

  return (
    <div style={{ display: "flex", flexDirection: "column", position: "relative" }}>
      {/* Connector lines */}
      {depth > 0 && (
        <div style={{
          position: "absolute",
          left: depth * 20 - 12,
          top: 0,
          width: 12,
          height: "50%",
          borderLeft: "1px solid var(--border-default)",
          borderBottom: "1px solid var(--border-default)",
          pointerEvents: "none",
        }} />
      )}
      {depth > 0 && !isLast && (
        <div style={{
          position: "absolute",
          left: depth * 20 - 12,
          top: "50%",
          bottom: 0,
          borderLeft: "1px solid var(--border-default)",
          pointerEvents: "none",
        }} />
      )}

      {/* Node card */}
      <div
        style={{
          marginLeft: depth * 20,
          marginBottom: 6,
          background: "var(--bg-2)",
          border: `1px solid ${hasViolations ? "rgba(239,68,68,0.25)" : "var(--border-default)"}`,
          borderRadius: "var(--radius-md)",
          overflow: "hidden",
        }}
      >
        {/* Node header */}
        <div
          style={{
            padding: "8px 12px",
            display: "flex",
            alignItems: "center",
            gap: 8,
            borderBottom: expanded ? "1px solid var(--border-subtle)" : "none",
            cursor: hasChildren ? "pointer" : "default",
          }}
          onClick={() => hasChildren && setExpanded((x) => !x)}
        >
          {hasChildren && (
            <span style={{ fontSize: "10px", color: "var(--text-dim)", userSelect: "none", width: 12 }}>
              {expanded ? "▾" : "▸"}
            </span>
          )}

          {/* Run ID badge */}
          <span style={{
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            padding: "1px 6px",
            background: "var(--bg-4)",
            borderRadius: "var(--radius-sm)",
            color: "var(--text-secondary)",
          }}>
            #{node.id}
          </span>

          {/* Agent */}
          <span style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-primary)", flex: 1 }}>
            {node.agent_id}
          </span>

          {/* Status */}
          <span style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: statusColor, display: "flex", alignItems: "center" }}>
            {statusDot(node.completion_status)}
            {node.completion_status}
          </span>

          {/* Quality */}
          {qualityBar(node.quality_score)}

          {/* Contract version */}
          {node.contract_version && (
            <span style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              v{node.contract_version}
            </span>
          )}

          {/* Trust delta */}
          {node.trust_score_after !== null && (
            <span style={{ fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--blue)" }}>
              trust: {(node.trust_score_after ?? 0).toFixed(3)}
            </span>
          )}

          {/* Violations badge */}
          {hasViolations && (
            <span style={{
              fontSize: "11px",
              padding: "1px 6px",
              background: "var(--red-dim)",
              border: "1px solid rgba(239,68,68,0.2)",
              borderRadius: "var(--radius-sm)",
              color: "var(--red)",
              fontFamily: "var(--font-mono)",
            }}>
              {node.violations.length} violation{node.violations.length > 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Node detail (always visible) */}
        <div style={{ padding: "8px 12px", display: "flex", gap: 16, flexWrap: "wrap" }}>
          {/* Telemetry */}
          {[
            { label: "LATENCY", value: node.latency_ms !== null ? `${node.latency_ms}ms` : "—" },
            { label: "COST", value: node.cost_usd !== null ? `$${node.cost_usd.toFixed(4)}` : "—" },
            { label: "INPUT TKN", value: node.input_tokens !== null ? node.input_tokens.toLocaleString() : "—" },
            { label: "OUTPUT TKN", value: node.output_tokens !== null ? node.output_tokens.toLocaleString() : "—" },
            { label: "TIME", value: node.timestamp ? new Date(node.timestamp).toLocaleTimeString() : "—" },
          ].map((m) => (
            <div key={m.label} style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em", fontFamily: "var(--font-mono)" }}>{m.label}</span>
              <span style={{ fontSize: "12px", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{m.value}</span>
            </div>
          ))}

          {/* Violations inline */}
          {hasViolations && (
            <div style={{ flex: "1 1 300px", marginTop: 4 }}>
              {node.violations.map((v, i) => (
                <div
                  key={i}
                  style={{
                    padding: "4px 8px",
                    background: "var(--red-dim)",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-mono)",
                    fontSize: "10px",
                    color: "var(--red)",
                    marginBottom: 3,
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  <span style={{
                    padding: "1px 4px",
                    background: v.blocked ? "rgba(239,68,68,0.2)" : "rgba(251,191,36,0.15)",
                    borderRadius: 2,
                    fontSize: "10px",
                    color: v.blocked ? "var(--red)" : "var(--amber)",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                  }}>
                    {v.blocked ? "BLOCKED" : "AUDITED"}
                  </span>
                  <span style={{ color: "var(--text-secondary)" }}>{v.policy_rule}</span>
                  <span style={{ color: "var(--text-dim)" }}>→ {v.action_attempted}</span>
                </div>
              ))}
            </div>
          )}

          {/* Context metrics inline */}
          {node.context_metrics.length > 0 && (
            <div style={{ flex: "1 1 300px", marginTop: 4 }}>
              <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em", fontFamily: "var(--font-mono)", display: "block", marginBottom: 4 }}>
                CONTEXT ROUTING
              </span>
              {node.context_metrics.map((cm, i) => {
                const savings = cm.tokens_available > 0
                  ? Math.round((1 - cm.tokens_sent / cm.tokens_available) * 100)
                  : 0;
                return (
                  <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 3, fontFamily: "var(--font-mono)", fontSize: "10px" }}>
                    <span style={{ color: "var(--text-secondary)" }}>{cm.subagent_id}</span>
                    <span style={{ color: "var(--text-dim)" }}>{cm.tokens_sent.toLocaleString()} / {cm.tokens_available.toLocaleString()} tkn</span>
                    <span style={{ color: "var(--green)" }}>−{savings}%</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Children */}
      {hasChildren && expanded && (
        <div style={{ display: "flex", flexDirection: "column", position: "relative" }}>
          {/* Vertical line for children continuation */}
          {node.children.length > 1 && (
            <div style={{
              position: "absolute",
              left: depth * 20 + 8,
              top: 0,
              bottom: 0,
              borderLeft: "1px solid var(--border-subtle)",
              pointerEvents: "none",
            }} />
          )}
          {node.children.map((child, idx) => (
            <RunNode
              key={child.id}
              node={child}
              depth={depth + 1}
              isLast={idx === node.children.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────
export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const runId = parseInt(params.id, 10);
  const invalidRunId = Number.isNaN(runId);

  const [run, setRun] = useState<RunRecord | null>(null);
  const [tree, setTree] = useState<RunTreeNode | null>(null);
  const [spans, setSpans] = useState<RunSpansResponse | null>(null);
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [prompts, setPrompts] = useState<PromptSnapshot[]>([]);
  const [view, setView] = useState<"execution" | "spans" | "waterfall" | "prompts">("spans");
  const [loading, setLoading] = useState(!invalidRunId);
  const [error, setError] = useState<string | null>(invalidRunId ? "Invalid run ID" : null);

  useEffect(() => {
    if (invalidRunId) return;

    function loadRun() {
      Promise.all([getRun(runId), getRunTree(runId), getRunSpans(runId), getRunMetrics(runId), getRunPrompts(runId)])
        .then(([r, t, s, m, p]) => {
          setRun(r);
          setTree(t);
          setSpans(s);
          setMetrics(m);
          setPrompts(p);
          setLoading(false);
        })
        .catch(() => {
          setError("Run not found");
          setLoading(false);
        });
    }

    loadRun();
  }, [invalidRunId, runId]);

  const totalNodes = (node: RunTreeNode | null): number => {
    if (!node) return 0;
    return 1 + node.children.reduce((s, c) => s + totalNodes(c), 0);
  };

  const totalViolations = (node: RunTreeNode | null): number => {
    if (!node) return 0;
    return node.violations.length + node.children.reduce((s, c) => s + totalViolations(c), 0);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--bg-0)",
        color: "var(--text-primary)",
        fontFamily: "var(--font-mono)",
      }}
    >
      {/* Topbar */}
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 50,
          background: "var(--bg-0)",
          borderBottom: "1px solid var(--border-default)",
          padding: "0 24px",
          height: 48,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => router.back()}
            style={{
              all: "unset",
              cursor: "pointer",
              fontSize: "11px",
              color: "var(--text-dim)",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            ← back
          </button>
          <span style={{ fontSize: "11px", color: "var(--border-default)" }}>|</span>
          <span
            style={{
              fontSize: "15px",
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--amber)",
              fontFamily: "var(--font-mono)",
            }}
          >
            NORMA
          </span>
          <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
            / runs / #{runId}
          </span>
        </div>
        <ModeToggle />
      </header>

      {/* Main */}
      <main style={{ maxWidth: 1200, margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>
        {loading && (
          <div style={{ color: "var(--text-dim)", fontSize: "12px", padding: "40px 0" }}>
            loading run #{runId}...
          </div>
        )}

        {error && (
          <div style={{
            padding: "12px 16px",
            background: "var(--red-dim)",
            border: "1px solid rgba(239,68,68,0.2)",
            borderRadius: "var(--radius-md)",
            color: "var(--red)",
            fontSize: "12px",
          }}>
            {error}
          </div>
        )}

        {run && (
          <>
            {/* Run header */}
            <div style={{
              background: "var(--bg-2)",
              border: `1px solid ${run.violations.length > 0 ? "rgba(239,68,68,0.25)" : "var(--border-default)"}`,
              borderRadius: "var(--radius-md)",
              padding: "16px 20px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: "20px", fontWeight: 700, fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>
                    Run #{run.id}
                  </span>
                  <span style={{
                    padding: "3px 10px",
                    background: `${STATUS_COLOR[run.completion_status] ?? "var(--text-dim)"}15`,
                    border: `1px solid ${STATUS_COLOR[run.completion_status] ?? "var(--text-dim)"}30`,
                    borderRadius: "var(--radius-sm)",
                    color: STATUS_COLOR[run.completion_status] ?? "var(--text-dim)",
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                  }}>
                    {run.completion_status}
                  </span>
                  {run.violations.length > 0 && (
                    <span style={{
                      padding: "3px 10px",
                      background: "var(--red-dim)",
                      border: "1px solid rgba(239,68,68,0.2)",
                      borderRadius: "var(--radius-sm)",
                      color: "var(--red)",
                      fontSize: "10px",
                      fontFamily: "var(--font-mono)",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}>
                      {run.violations.length} VIOLATION{run.violations.length > 1 ? "S" : ""}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => router.push(`/agents/${run.agent_id}`)}
                  style={{
                    all: "unset",
                    cursor: "pointer",
                    fontSize: "11px",
                    color: "var(--amber)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {run.agent_id} →
                </button>
              </div>

              {/* Metrics strip — 2 rows × 4 columns */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
                {[
                  { label: "CONTRACT", value: run.contract_version ? `v${run.contract_version}` : "—" },
                  { label: "QUALITY", value: run.quality_score !== null ? `${Math.round(run.quality_score * 100)}%` : "—", color: run.quality_score !== null ? (run.quality_score >= 0.8 ? "var(--green)" : run.quality_score >= 0.6 ? "var(--amber)" : "var(--red)") : undefined },
                  { label: "TRUST AFTER", value: run.trust_score_after !== null ? run.trust_score_after.toFixed(3) : "—", color: "var(--blue)" },
                  { label: "LATENCY", value: run.latency_ms !== null ? `${run.latency_ms}ms` : "—" },
                  { label: "COST", value: run.cost_usd !== null ? `$${run.cost_usd.toFixed(4)}` : "—" },
                  { label: "IN TOKENS", value: run.input_tokens !== null ? run.input_tokens.toLocaleString() : "—" },
                  { label: "OUT TOKENS", value: run.output_tokens !== null ? run.output_tokens.toLocaleString() : "—" },
                  { label: "TIME", value: run.timestamp ? new Date(run.timestamp).toLocaleTimeString() : "—" },
                ].map((m) => (
                  <div
                    key={m.label}
                    style={{
                      padding: "8px 10px",
                      background: "var(--bg-1)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      display: "flex",
                      flexDirection: "column",
                      gap: 3,
                    }}
                  >
                    <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.07em", textTransform: "uppercase" }}>{m.label}</span>
                    <span style={{ fontSize: "13px", fontWeight: 500, color: m.color ?? "var(--text-primary)" }}>{m.value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quality breakdown */}
            <QualityBreakdownPanel
              score={run.quality_score}
              rationale={run.quality_rationale ?? null}
              breakdown={run.quality_breakdown ?? null}
            />

            {/* Execution tree */}
            {((view === "execution" && tree) || (view === "spans" && spans) || (view === "waterfall" && spans) || (view === "prompts")) && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <button
                      onClick={() => setView("spans")}
                      style={{
                        padding: "3px 9px",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-default)",
                        background: view === "spans" ? "var(--bg-4)" : "transparent",
                        color: view === "spans" ? "var(--amber)" : "var(--text-dim)",
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        cursor: "pointer",
                      }}
                    >
                      SPAN TREE
                    </button>
                    <button
                      onClick={() => setView("waterfall")}
                      style={{
                        padding: "3px 9px",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-default)",
                        background: view === "waterfall" ? "var(--bg-4)" : "transparent",
                        color: view === "waterfall" ? "var(--amber)" : "var(--text-dim)",
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        cursor: "pointer",
                      }}
                    >
                      WATERFALL
                    </button>
                    <button
                      onClick={() => setView("prompts")}
                      style={{
                        padding: "3px 9px",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-default)",
                        background: view === "prompts" ? "var(--bg-4)" : "transparent",
                        color: view === "prompts" ? "var(--amber)" : "var(--text-dim)",
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        cursor: "pointer",
                      }}
                    >
                      PROMPTS
                    </button>
                    <button
                      onClick={() => setView("execution")}
                      style={{
                        padding: "3px 9px",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-default)",
                        background: view === "execution" ? "var(--bg-4)" : "transparent",
                        color: view === "execution" ? "var(--amber)" : "var(--text-dim)",
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        cursor: "pointer",
                      }}
                    >
                      RUN TREE
                    </button>
                  </div>
                  <div style={{ display: "flex", gap: 10 }}>
                    <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                      {view === "execution" ? `${totalNodes(tree)} node${totalNodes(tree) !== 1 ? "s" : ""}` : view === "prompts" ? `${prompts.length} snapshot${prompts.length !== 1 ? "s" : ""}` : `${spans?.span_count ?? 0} span${(spans?.span_count ?? 0) !== 1 ? "s" : ""}`}
                    </span>
                    {view === "execution" && totalViolations(tree) > 0 && (
                      <span style={{ fontSize: "10px", color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                        {totalViolations(tree)} violation{totalViolations(tree) !== 1 ? "s" : ""}
                      </span>
                    )}
                    {metrics && view === "spans" && (
                      <>
                        <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                          in:{metrics.token_metrics.input_tokens} out:{metrics.token_metrics.output_tokens}
                        </span>
                        <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                          ${metrics.cost_metrics.total_cost_usd.toFixed(5)}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                {view === "execution" && tree && <RunNode node={tree} depth={0} isLast={true} />}
                {view === "spans" && spans && <SpanTree roots={spans.tree} />}
                {view === "waterfall" && spans && <WaterfallTimeline spans={spans.spans} />}
                {view === "prompts" && <PromptInspector prompts={prompts} />}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
