"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getAgentRecentRuns } from "@/lib/api";

interface EnforcementEvent {
  type: "blocked" | "audited";
  policy_rule: string;
  action_attempted: string;
  event_type: string;
}

interface RunRow {
  run_id: number;
  parent_run_id: number | null;
  initiated_by: string | null;
  timestamp: string | null;
  status: string;
  quality_score: number | null;
  trust_score_after: number | null;
  latency_ms: number | null;
  cost_usd: number | null;
  contract_version: string | null;
  enforcement_events: EnforcementEvent[];
}

function TrustDelta({ prev, curr }: { prev: number | null; curr: number | null }) {
  if (prev === null || curr === null) return null;
  const delta = curr - prev;
  if (Math.abs(delta) < 0.001) return <span style={{ color: "var(--text-dim)", fontSize: "10px" }}>—</span>;
  const up = delta > 0;
  return (
    <span style={{ color: up ? "var(--green)" : "var(--red)", fontSize: "10px", fontFamily: "var(--font-mono)" }}>
      {up ? "+" : ""}{(delta * 100).toFixed(1)}pp
    </span>
  );
}

function InitiatedByBadge({ value }: { value: string | null }) {
  if (!value) return <span style={{ fontSize: "9px", color: "var(--text-dim)" }}>—</span>;
  let label: string;
  let color: string;
  let icon: string;
  if (value === "user") { label = "user"; color = "var(--blue, #60a5fa)"; icon = "👤"; }
  else if (value === "api") { label = "api"; color = "var(--text-secondary)"; icon = "⌘"; }
  else if (value.startsWith("orchestrator:")) {
    const parent = value.replace("orchestrator:", "");
    label = parent.length > 16 ? parent.slice(0, 14) + "…" : parent;
    color = "var(--amber)";
    icon = "⚙";
  } else { label = value; color = "var(--text-dim)"; icon = "·"; }
  return (
    <span title={value} style={{
      fontSize: "8px", letterSpacing: "0.04em", padding: "1px 5px",
      background: "var(--bg-1)", border: "1px solid var(--border-subtle)",
      borderRadius: 3, color, fontFamily: "var(--font-mono)",
      whiteSpace: "nowrap", display: "inline-flex", alignItems: "center", gap: 3,
    }}>
      <span style={{ fontSize: "9px" }}>{icon}</span>{label}
    </span>
  );
}

export function RunTimeline({ agentId, limit = 30 }: { agentId: string; limit?: number }) {
  const router = useRouter();
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [expandedParents, setExpandedParents] = useState<Set<number>>(new Set());
  const loading = runs === null;

  useEffect(() => {
    getAgentRecentRuns(agentId, limit).then(setRuns).catch(() => setRuns([]));
  }, [agentId, limit]);

  const runItems = runs ?? [];

  // Separate top-level vs child runs
  const topLevel = runItems.filter((r) => r.parent_run_id === null);
  const childMap = new Map<number, RunRow[]>();
  for (const r of runItems) {
    if (r.parent_run_id !== null) {
      const children = childMap.get(r.parent_run_id) || [];
      children.push(r);
      childMap.set(r.parent_run_id, children);
    }
  }

  // runs come newest-first from API; reverse for timeline display (oldest → newest)
  const ordered = [...topLevel].reverse();

  const toggleParent = (runId: number) => {
    setExpandedParents((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  };

  return (
    <div
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-md)",
        fontFamily: "var(--font-mono)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <button
        onClick={() => setExpanded((e) => !e)}
        style={{
          all: "unset",
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          width: "100%",
          padding: "10px 14px",
          borderBottom: expanded ? "1px solid var(--border-subtle)" : "none",
          boxSizing: "border-box",
        }}
      >
        <span style={{ fontSize: "11px", color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Run Timeline · {agentId}
        </span>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {!loading && runItems.length > 0 && (
            <>
              <span style={{ fontSize: "9px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
                {runItems.filter((r) => r.status === "failed").length} violation{runItems.filter((r) => r.status === "failed").length !== 1 ? "s" : ""}
              </span>
              <span style={{ fontSize: "9px", color: "var(--text-dim)" }}>·</span>
              <span style={{ fontSize: "9px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
                {topLevel.length} workflow{topLevel.length !== 1 ? "s" : ""}
              </span>
            </>
          )}
          <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>{expanded ? "▾" : "▸"}</span>
        </div>
      </button>

      {expanded && (
        <>
          {loading && (
            <div style={{ padding: "20px 14px", color: "var(--text-dim)", fontSize: "11px", letterSpacing: "0.06em" }}>
              loading runs…
            </div>
          )}

          {!loading && runItems.length === 0 && (
            <div style={{ padding: "20px 14px", color: "var(--text-dim)", fontSize: "11px" }}>
              No runs recorded for this agent yet. Run{" "}
              <code style={{ color: "var(--amber)", fontSize: "10px" }}>poetry run norma-watch</code>{" "}
              to generate runs.
            </div>
          )}

          {!loading && runItems.length > 0 && (
            <>
              {/* Sparkline bar */}
              <div
                style={{
                  padding: "8px 14px 6px",
                  display: "flex",
                  alignItems: "flex-end",
                  gap: 2,
                  borderBottom: "1px solid var(--border-subtle)",
                }}
              >
                {ordered.map((r) => {
                  const h = r.trust_score_after !== null ? Math.max(6, Math.round(r.trust_score_after * 40)) : 8;
                  const blocked = r.enforcement_events.some((e) => e.type === "blocked");
                  const color = blocked ? "var(--red)" : r.status === "success" ? "var(--green)" : "var(--amber)";
                  return (
                    <div
                      key={r.run_id}
                      title={`Run #${r.run_id} — trust: ${r.trust_score_after?.toFixed(3) ?? "?"} — ${r.status}`}
                      style={{
                        flex: 1,
                        height: h,
                        background: color,
                        opacity: 0.7,
                        borderRadius: "1px 1px 0 0",
                        transition: "opacity 0.1s",
                        cursor: "default",
                        maxWidth: 16,
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = "1"; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.opacity = "0.7"; }}
                    />
                  );
                })}
                <span style={{ fontSize: "9px", color: "var(--text-dim)", paddingLeft: 4, paddingBottom: 0, letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
                  trust over time
                </span>
              </div>

              {/* Table */}
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px" }}>
                  <thead>
                    <tr style={{ background: "var(--bg-1)" }}>
                      {["", "Run", "Time", "Initiated", "Status", "Trust", "Δ", "Quality", "Latency", "Enforcement"].map((h) => (
                        <th key={h} style={{
                          padding: "5px 8px",
                          textAlign: "left",
                          fontSize: "9px",
                          color: "var(--text-dim)",
                          fontWeight: 400,
                          letterSpacing: "0.07em",
                          textTransform: "uppercase",
                          whiteSpace: "nowrap",
                        }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ordered.map((r, i) => {
                      const prev = i > 0 ? ordered[i - 1].trust_score_after : null;
                      const blocked = r.enforcement_events.some((e) => e.type === "blocked");
                      const ts = r.timestamp ? new Date(r.timestamp) : null;
                      const timeStr = ts
                        ? ts.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
                        : "—";
                      const children = childMap.get(r.run_id) || [];
                      const hasChildren = children.length > 0;
                      const isParentExpanded = expandedParents.has(r.run_id);

                      return (
                        <React.Fragment key={r.run_id}>
                          {/* Parent / top-level row */}
                          <tr
                            style={{
                              borderTop: "1px solid var(--border-subtle)",
                              background: blocked ? "rgba(239,68,68,0.03)" : "transparent",
                              cursor: "pointer",
                            }}
                            onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = blocked ? "rgba(239,68,68,0.07)" : "var(--bg-3)"; }}
                            onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = blocked ? "rgba(239,68,68,0.03)" : "transparent"; }}
                          >
                            <td
                              style={{ padding: "7px 4px 7px 10px", width: 20, cursor: hasChildren ? "pointer" : "default" }}
                              onClick={(e) => { if (hasChildren) { e.stopPropagation(); toggleParent(r.run_id); } }}
                            >
                              {hasChildren ? (
                                <span style={{ fontSize: "10px", color: "var(--amber)", userSelect: "none" }}>
                                  {isParentExpanded ? "▾" : "▸"}
                                </span>
                              ) : (
                                <span style={{ fontSize: "10px", color: "var(--text-dim)", opacity: 0.3 }}>·</span>
                              )}
                            </td>
                            <td style={{ padding: "7px 8px", color: "var(--text-secondary)" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              #{r.run_id}
                              {hasChildren && (
                                <span style={{ fontSize: "8px", color: "var(--amber)", marginLeft: 4 }}>+{children.length}</span>
                              )}
                            </td>
                            <td style={{ padding: "7px 8px", color: "var(--text-dim)", whiteSpace: "nowrap" }} onClick={() => router.push(`/runs/${r.run_id}`)}>{timeStr}</td>
                            <td style={{ padding: "7px 8px" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              <InitiatedByBadge value={r.initiated_by} />
                            </td>
                            <td style={{ padding: "7px 8px" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              <span style={{ fontSize: "9px", letterSpacing: "0.06em", textTransform: "uppercase", color: r.status === "success" ? "var(--green)" : "var(--red)" }}>
                                {r.status}
                              </span>
                            </td>
                            <td style={{ padding: "7px 8px", color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              {r.trust_score_after?.toFixed(3) ?? "—"}
                            </td>
                            <td style={{ padding: "7px 8px" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              <TrustDelta prev={prev} curr={r.trust_score_after} />
                            </td>
                            <td style={{ padding: "7px 8px", color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              {r.quality_score !== null ? `${(r.quality_score * 100).toFixed(0)}%` : "—"}
                            </td>
                            <td style={{ padding: "7px 8px", color: "var(--text-secondary)", fontVariantNumeric: "tabular-nums" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              {r.latency_ms !== null ? `${r.latency_ms}ms` : "—"}
                            </td>
                            <td style={{ padding: "7px 8px" }} onClick={() => router.push(`/runs/${r.run_id}`)}>
                              {blocked ? (
                                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                                  {r.enforcement_events.filter((e) => e.type === "blocked").slice(0, 2).map((ev, ei) => (
                                    <span key={ei} title={ev.action_attempted} style={{
                                      fontSize: "9px", padding: "1px 6px", background: "rgba(239,68,68,0.1)",
                                      color: "var(--red)", border: "1px solid rgba(239,68,68,0.2)",
                                      borderRadius: "var(--radius-sm)", letterSpacing: "0.04em",
                                      whiteSpace: "nowrap", maxWidth: 180, overflow: "hidden",
                                      textOverflow: "ellipsis", display: "block",
                                    }}>
                                      ✗ {ev.policy_rule ?? ev.action_attempted}
                                    </span>
                                  ))}
                                </div>
                              ) : (
                                <span style={{ fontSize: "9px", color: "var(--text-dim)" }}>—</span>
                              )}
                            </td>
                          </tr>

                          {/* Expanded child rows (sub-agent runs) */}
                          {isParentExpanded && children.sort((a, b) => a.run_id - b.run_id).map((child) => {
                            const cBlocked = child.enforcement_events.some((e) => e.type === "blocked");
                            const cTs = child.timestamp ? new Date(child.timestamp) : null;
                            const cTimeStr = cTs ? cTs.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
                            return (
                              <tr
                                key={child.run_id}
                                onClick={() => router.push(`/runs/${child.run_id}`)}
                                style={{
                                  borderTop: "1px solid var(--border-subtle)",
                                  background: cBlocked ? "rgba(239,68,68,0.02)" : "rgba(245,158,11,0.02)",
                                  cursor: "pointer",
                                }}
                                onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = cBlocked ? "rgba(239,68,68,0.06)" : "rgba(245,158,11,0.06)"; }}
                                onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = cBlocked ? "rgba(239,68,68,0.02)" : "rgba(245,158,11,0.02)"; }}
                              >
                                <td style={{ padding: "5px 4px 5px 10px" }}>
                                  <span style={{ fontSize: "9px", color: "var(--amber)", opacity: 0.4 }}>└</span>
                                </td>
                                <td style={{ padding: "5px 8px", color: "var(--text-dim)", fontSize: "10px" }}>#{child.run_id}</td>
                                <td style={{ padding: "5px 8px", color: "var(--text-dim)", fontSize: "10px", whiteSpace: "nowrap" }}>{cTimeStr}</td>
                                <td style={{ padding: "5px 8px" }}><InitiatedByBadge value={child.initiated_by} /></td>
                                <td style={{ padding: "5px 8px" }}>
                                  <span style={{ fontSize: "8px", letterSpacing: "0.06em", textTransform: "uppercase", color: child.status === "success" ? "var(--green)" : "var(--red)" }}>
                                    {child.status}
                                  </span>
                                </td>
                                <td style={{ padding: "5px 8px", color: "var(--text-dim)", fontSize: "10px", fontVariantNumeric: "tabular-nums" }}>
                                  {child.trust_score_after?.toFixed(3) ?? "—"}
                                </td>
                                <td style={{ padding: "5px 8px" }}><span style={{ fontSize: "9px", color: "var(--text-dim)" }}>—</span></td>
                                <td style={{ padding: "5px 8px", color: "var(--text-dim)", fontSize: "10px", fontVariantNumeric: "tabular-nums" }}>
                                  {child.quality_score !== null ? `${(child.quality_score * 100).toFixed(0)}%` : "—"}
                                </td>
                                <td style={{ padding: "5px 8px", color: "var(--text-dim)", fontSize: "10px", fontVariantNumeric: "tabular-nums" }}>
                                  {child.latency_ms !== null ? `${child.latency_ms}ms` : "—"}
                                </td>
                                <td style={{ padding: "5px 8px" }}>
                                  {cBlocked ? (
                                    <span style={{ fontSize: "8px", padding: "1px 5px", background: "rgba(239,68,68,0.1)", color: "var(--red)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 3 }}>✗ blocked</span>
                                  ) : (
                                    <span style={{ fontSize: "9px", color: "var(--text-dim)" }}>—</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Footer */}
              <div
                style={{
                  padding: "8px 14px",
                  borderTop: "1px solid var(--border-subtle)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span style={{ fontSize: "9px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
                  {topLevel.length} workflow{topLevel.length !== 1 ? "s" : ""} · {runItems.length} total run{runItems.length !== 1 ? "s" : ""}
                </span>
                <a
                  href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080"}/api/agents/${agentId}/export/compliance`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    fontSize: "9px",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-dim)",
                    textDecoration: "none",
                    padding: "3px 8px",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-sm)",
                    transition: "color 0.15s, border-color 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLAnchorElement).style.color = "var(--amber)";
                    (e.currentTarget as HTMLAnchorElement).style.borderColor = "rgba(245,158,11,0.3)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLAnchorElement).style.color = "var(--text-dim)";
                    (e.currentTarget as HTMLAnchorElement).style.borderColor = "var(--border-subtle)";
                  }}
                >
                  ↓ compliance CSV
                </a>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
