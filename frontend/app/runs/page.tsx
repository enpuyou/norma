"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { ModeToggle } from "@/components/ModeToggle";
import { getRuns, getRunSteps, type RunRecord, type RunStep } from "@/lib/api";

// ─── Status helpers ────────────────────────────────────────────────────────────
const STATUS_COLOR: Record<string, string> = {
  success:   "var(--green)",
  failed:    "var(--red)",
  timeout:   "var(--amber)",
  escalated: "var(--blue)",
};

function statusDot(status: string) {
  return (
    <span style={{
      display: "inline-block",
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: STATUS_COLOR[status] ?? "var(--text-dim)",
      marginRight: 6,
      flexShrink: 0,
    }} />
  );
}

function qBadge(score: number | null) {
  if (score === null) return <span style={{ color: "var(--text-dim)" }}>—</span>;
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--amber)" : "var(--red)";
  return <span style={{ color, fontFamily: "var(--font-mono)", fontSize: 11 }}>{pct}%</span>;
}

function trustBadge(score: number | null) {
  if (score === null) return <span style={{ color: "var(--text-dim)" }}>—</span>;
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)";
  return <span style={{ color, fontFamily: "var(--font-mono)", fontSize: 11 }}>{pct}%</span>;
}

function fmtLatency(ms: number | null) {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function fmtTs(ts: string | null) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    return d.toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

// ─── Run Step Drawer ───────────────────────────────────────────────────────────
function RunStepDrawer({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [steps, setSteps] = useState<RunStep[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loading = steps === null && error === null;

  useEffect(() => {
    let active = true;
    getRunSteps(runId)
      .then((result) => {
        if (!active) return;
        setSteps(result);
        setError(null);
      })
      .catch((e) => {
        if (!active) return;
        setError(e.message ?? "Failed to load steps");
      });

    return () => {
      active = false;
    };
  }, [runId]);

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, width: 460, height: "100vh",
      background: "var(--bg-2)", borderLeft: "1px solid var(--border-default)",
      display: "flex", flexDirection: "column", zIndex: 100, overflowY: "auto",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "13px 16px", borderBottom: "1px solid var(--border-default)",
        position: "sticky", top: 0, background: "var(--bg-2)",
      }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-default)", letterSpacing: "0.06em" }}>
          STEP TRACE — RUN #{runId}
        </span>
        <button
          onClick={onClose}
          style={{
            background: "transparent", border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-sm)", color: "var(--text-dim)",
            fontFamily: "var(--font-mono)", fontSize: 9, padding: "3px 9px", cursor: "pointer",
          }}
        >
          CLOSE ✕
        </button>
      </div>
      <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
        {loading && <p style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>Loading…</p>}
        {error && <p style={{ fontSize: 11, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{error}</p>}
        {!loading && !error && (steps?.length ?? 0) === 0 && (
          <p style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>No step data for this run.</p>
        )}
        {(steps ?? []).map((step) => (
          <div key={step.id} style={{
            background: "var(--bg-3)",
            border: `1px solid ${step.blocked ? "rgba(239,68,68,0.3)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-md)", padding: "10px 12px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600,
                color: step.blocked ? "var(--red)" : "var(--text-default)",
              }}>
                #{step.step_index + 1} {step.tool_name}
              </span>
              {step.blocked && (
                <span style={{
                  background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)",
                  borderRadius: 3, padding: "1px 6px", fontSize: 9,
                  fontFamily: "var(--font-mono)", color: "var(--red)",
                }}>BLOCKED</span>
              )}
              {step.latency_ms !== null && !step.blocked && (
                <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)", marginLeft: "auto" }}>
                  {step.latency_ms}ms
                </span>
              )}
            </div>
            {step.policy_rule && (
              <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--amber)", marginBottom: 5 }}>
                rule: {step.policy_rule}
              </div>
            )}
            <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>IN  </span>
              <span style={{ fontFamily: "var(--font-mono)" }}>{step.input_text ?? "—"}</span>
            </div>
            {step.output_text && (
              <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>OUT </span>
                <span style={{ fontFamily: "var(--font-mono)" }}>{step.output_text}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Filter bar ────────────────────────────────────────────────────────────────
function FilterBar({
  agentFilter, setAgentFilter,
  statusFilter, setStatusFilter,
  agentIds,
}: {
  agentFilter: string;
  setAgentFilter: (v: string) => void;
  statusFilter: string;
  setStatusFilter: (v: string) => void;
  agentIds: string[];
}) {
  const inputStyle: React.CSSProperties = {
    background: "var(--bg-3)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-sm)",
    color: "var(--text-default)",
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    padding: "5px 10px",
    outline: "none",
    cursor: "pointer",
  };

  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
      <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} style={inputStyle}>
        <option value="">ALL AGENTS</option>
        {agentIds.map((id) => (
          <option key={id} value={id}>{id}</option>
        ))}
      </select>
      <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={inputStyle}>
        <option value="">ALL STATUSES</option>
        <option value="success">SUCCESS</option>
        <option value="failed">FAILED</option>
        <option value="timeout">TIMEOUT</option>
        <option value="escalated">ESCALATED</option>
      </select>
    </div>
  );
}

// ─── Main page component ───────────────────────────────────────────────────────
export default function RunsPage() {
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [agentFilter, setAgentFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const loading = runs === null && error === null;

  const load = useCallback((reset = false) => {
    if (reset) {
      setRuns(null);
      setError(null);
    }
    getRuns(agentFilter || undefined, 250)
      .then(setRuns)
      .catch((e) => setError(e.message ?? "Failed to load runs"));
  }, [agentFilter]);

  useEffect(() => {
    let active = true;
    getRuns(agentFilter || undefined, 250)
      .then((result) => {
        if (!active) return;
        setRuns(result);
        setError(null);
      })
      .catch((e) => {
        if (!active) return;
        setError(e.message ?? "Failed to load runs");
      });

    return () => {
      active = false;
    };
  }, [agentFilter]);

  const runItems = runs ?? [];

  const agentIds = Array.from(new Set(runItems.map((r) => r.agent_id))).sort();

  const filtered = statusFilter
    ? runItems.filter((r) => r.completion_status === statusFilter)
    : runItems;

  const totalViolations = filtered.reduce((n, r) => n + (r.violations?.length ?? 0), 0);
  const blockedViolations = filtered.reduce(
    (n, r) => n + (r.violations?.filter((v) => v.blocked).length ?? 0),
    0,
  );
  const avgQuality =
    filtered.length > 0
      ? filtered.reduce((s, r) => s + (r.quality_score ?? 0), 0) / filtered.length
      : null;

  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--bg-1)",
      color: "var(--text-default)",
      fontFamily: "var(--font-sans)",
    }}>
      {/* Header */}
      <header style={{
        borderBottom: "1px solid var(--border-default)",
        background: "var(--bg-2)",
        padding: "0 24px",
        height: 52,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        position: "sticky",
        top: 0,
        zIndex: 60,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <Link href="/" style={{ textDecoration: "none" }}>
            <span style={{
              fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600,
              color: "var(--text-default)", letterSpacing: "0.04em",
            }}>norma.ai</span>
          </Link>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {[
              { label: "DASHBOARD", href: "/", active: false },
              { label: "REGISTRY", href: "/agents", active: false },
              { label: "LOG", href: "/runs", active: true },
              { label: "ALERTS", href: "/alerts", active: false },
              { label: "COMPLIANCE", href: "/compliance", active: false },
            ].map((item) => (
              <Link
                key={item.label}
                href={item.href}
                style={{
                  fontSize: "10px",
                  color: item.active ? "var(--amber)" : "var(--text-dim)",
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                  textDecoration: "none",
                  fontFamily: "var(--font-mono)",
                  border: item.active ? "1px solid rgba(245,158,11,0.3)" : "1px solid var(--border-subtle)",
                  background: item.active ? "var(--amber-glow)" : "transparent",
                  borderRadius: "var(--radius-sm)",
                  padding: "3px 8px",
                }}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => load(true)}
            style={{
              background: "transparent",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-dim)",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              padding: "4px 10px",
              cursor: "pointer",
              letterSpacing: "0.06em",
            }}
          >
            ↺ REFRESH
          </button>
          <ModeToggle />
        </div>
      </header>

      {/* Main content */}
      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "24px 24px 48px" }}>

        {/* Summary stats */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}>
          {[
            { label: "TOTAL RUNS", value: filtered.length.toString() },
            { label: "VIOLATIONS", value: totalViolations.toString(), accent: totalViolations > 0 ? "var(--red)" : undefined },
            { label: "BLOCKED", value: blockedViolations.toString(), accent: blockedViolations > 0 ? "var(--amber)" : undefined },
            { label: "AVG QUALITY", value: avgQuality != null ? `${Math.round(avgQuality * 100)}%` : "—" },
          ].map(({ label, value, accent }) => (
            <div key={label} style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-md)",
              padding: "14px 16px",
            }}>
              <div style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)", letterSpacing: "0.08em", marginBottom: 6 }}>
                {label}
              </div>
              <div style={{ fontSize: 22, fontFamily: "var(--font-mono)", fontWeight: 600, color: accent ?? "var(--text-default)" }}>
                {value}
              </div>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div style={{
          background: "var(--bg-2)",
          border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-md)",
          padding: "12px 16px",
          marginBottom: 16,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 10,
        }}>
          <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)", letterSpacing: "0.08em" }}>
            FILTER
          </span>
          <FilterBar
            agentFilter={agentFilter}
            setAgentFilter={setAgentFilter}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            agentIds={agentIds}
          />
          <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
            {filtered.length} run{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Run table */}
        <div style={{
          background: "var(--bg-2)",
          border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-md)",
          overflow: "hidden",
        }}>
          {loading && (
            <div style={{ padding: "32px 20px", textAlign: "center", fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              Loading runs…
            </div>
          )}
          {error && (
            <div style={{ padding: "20px", fontSize: 11, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
              {error}
            </div>
          )}
          {!loading && !error && filtered.length === 0 && (
            <div style={{ padding: "32px 20px", textAlign: "center", fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              No runs found.
            </div>
          )}
          {!loading && !error && filtered.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-default)" }}>
                  {["RUN", "AGENT", "CONTRACT", "STATUS", "QUALITY", "TRUST", "LATENCY", "VIOLATIONS", "TOKENS", "TIMESTAMP"].map((h) => (
                    <th key={h} style={{
                      padding: "9px 14px",
                      textAlign: "left",
                      fontSize: 9,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-dim)",
                      fontWeight: 500,
                      letterSpacing: "0.08em",
                      whiteSpace: "nowrap",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((run) => {
                  const violationCount = run.violations?.length ?? 0;
                  const isSelected = selectedRunId === run.id;
                  return (
                    <tr
                      key={run.id}
                      onClick={() => setSelectedRunId(isSelected ? null : run.id)}
                      style={{
                        borderBottom: "1px solid var(--border-subtle)",
                        cursor: "pointer",
                        background: isSelected ? "var(--bg-3)" : "transparent",
                        transition: "background 0.1s",
                      }}
                      onMouseEnter={(e) => {
                        if (!isSelected) (e.currentTarget as HTMLElement).style.background = "var(--bg-3)";
                      }}
                      onMouseLeave={(e) => {
                        if (!isSelected) (e.currentTarget as HTMLElement).style.background = "transparent";
                      }}
                    >
                      <td style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                        <Link
                          href={`/runs/${run.id}`}
                          onClick={(e) => e.stopPropagation()}
                          style={{ color: "var(--blue)", textDecoration: "none" }}
                        >
                          #{run.id}
                        </Link>
                        {run.parent_run_id && (
                          <span style={{ fontSize: 9, color: "var(--text-dim)", marginLeft: 4 }}>
                            (↳{run.parent_run_id})
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px" }}>
                        <Link
                          href={`/agents/${run.agent_id}`}
                          onClick={(e) => e.stopPropagation()}
                          style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)", textDecoration: "none" }}
                        >
                          {run.agent_id}
                        </Link>
                      </td>
                      <td style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-dim)" }}>
                        {run.contract_version ? `v${run.contract_version}` : "—"}
                      </td>
                      <td style={{ padding: "8px 14px" }}>
                        <span style={{ display: "flex", alignItems: "center", fontFamily: "var(--font-mono)", fontSize: 10 }}>
                          {statusDot(run.completion_status)}
                          {run.completion_status}
                        </span>
                      </td>
                      <td style={{ padding: "8px 14px" }}>{qBadge(run.quality_score)}</td>
                      <td style={{ padding: "8px 14px" }}>{trustBadge(run.trust_score_after)}</td>
                      <td style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
                        {fmtLatency(run.latency_ms)}
                      </td>
                      <td style={{ padding: "8px 14px" }}>
                        {violationCount > 0 ? (
                          <span style={{
                            fontFamily: "var(--font-mono)", fontSize: 12,
                            color: "var(--red)",
                            background: "rgba(239,68,68,0.1)",
                            border: "1px solid rgba(239,68,68,0.3)",
                            borderRadius: 3,
                            padding: "1px 6px",
                          }}>
                            {violationCount}
                          </span>
                        ) : (
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-dim)" }}>0</span>
                        )}
                      </td>
                      <td style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-dim)" }}>
                        {run.input_tokens != null ? `${run.input_tokens}↑` : ""}
                        {run.output_tokens != null ? ` ${run.output_tokens}↓` : ""}
                        {run.input_tokens == null && run.output_tokens == null ? "—" : ""}
                      </td>
                      <td style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-dim)", whiteSpace: "nowrap" }}>
                        {fmtTs(run.timestamp)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Violation breakdown for filtered runs */}
        {filtered.some((r) => (r.violations?.length ?? 0) > 0) && (
          <div style={{
            marginTop: 20,
            background: "var(--bg-2)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            overflow: "hidden",
          }}>
            <div style={{
              padding: "10px 14px",
              borderBottom: "1px solid var(--border-default)",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              color: "var(--text-dim)",
              letterSpacing: "0.08em",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}>
              <span>VIOLATIONS</span>
              <span style={{ color: "var(--red)" }}>{totalViolations} total · {blockedViolations} blocked</span>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border-default)" }}>
                  {["RUN", "AGENT", "POLICY RULE", "ACTION", "BLOCKED"].map((h) => (
                    <th key={h} style={{
                      padding: "8px 14px",
                      textAlign: "left",
                      fontSize: 9,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-dim)",
                      fontWeight: 500,
                      letterSpacing: "0.08em",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.flatMap((run) =>
                  (run.violations ?? []).map((v, i) => (
                    <tr key={`${run.id}-${i}`} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      <td style={{ padding: "7px 14px", fontFamily: "var(--font-mono)", fontSize: 10 }}>
                        <Link href={`/runs/${run.id}`} style={{ color: "var(--blue)", textDecoration: "none" }}>
                          #{run.id}
                        </Link>
                      </td>
                      <td style={{ padding: "7px 14px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>
                        {run.agent_id}
                      </td>
                      <td style={{ padding: "7px 14px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--amber)" }}>
                        {v.policy_rule}
                      </td>
                      <td style={{ padding: "7px 14px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-dim)" }}>
                        {v.action_attempted}
                      </td>
                      <td style={{ padding: "7px 14px" }}>
                        {v.blocked ? (
                          <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--red)", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 3, padding: "1px 6px" }}>YES</span>
                        ) : (
                          <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>NO</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* Step drawer portal */}
      {selectedRunId != null && (
        <RunStepDrawer runId={selectedRunId} onClose={() => setSelectedRunId(null)} />
      )}
    </div>
  );
}
