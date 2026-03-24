"use client";

import { useState } from "react";
import type { Agent, Tier } from "@/lib/types";
import { useMode } from "@/hooks/useMode";
import { TrustSparkline } from "./TrustSparkline";

// ─── Tier badge ────────────────────────────────────────────────────────────────
const TIER_COLORS: Record<Tier, { text: string; bg: string; dot: string }> = {
  restricted: { text: "#ef4444", bg: "rgba(239,68,68,0.10)", dot: "#ef4444" },
  standard:   { text: "#60a5fa", bg: "rgba(96,165,250,0.10)", dot: "#60a5fa" },
  trusted:    { text: "#22c55e", bg: "rgba(34,197,94,0.10)",  dot: "#22c55e" },
};

function TierBadge({ tier }: { tier: Tier }) {
  const c = TIER_COLORS[tier];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 8px",
        background: c.bg,
        border: `1px solid ${c.text}30`,
        borderRadius: "var(--radius-sm)",
        color: c.text,
        fontSize: "10px",
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.1em",
        textTransform: "capitalize",
        fontWeight: 500,
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: c.dot,
          boxShadow: `0 0 4px ${c.dot}`,
          flexShrink: 0,
          display: "inline-block",
        }}
      />
      {tier}
    </span>
  );
}

// ─── Stat cell ─────────────────────────────────────────────────────────────────
function Stat({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: string | number;
  unit?: string;
  color?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span
        style={{
          fontSize: "10px",
          color: "var(--text-dim)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: "14px",
          fontFamily: "var(--font-mono)",
          fontWeight: 500,
          color: color ?? "var(--text-primary)",
          lineHeight: 1,
        }}
      >
        {value}
        {unit && (
          <span style={{ fontSize: "10px", color: "var(--text-dim)", marginLeft: 2 }}>
            {unit}
          </span>
        )}
      </span>
    </div>
  );
}

// ─── Trend arrow ───────────────────────────────────────────────────────────────
function TrendIndicator({ dir }: { dir: Agent["trend"] }) {
  if (dir === "up")     return <span style={{ color: "#22c55e", fontSize: 12 }}>↑</span>;
  if (dir === "down")   return <span style={{ color: "#ef4444", fontSize: 12 }}>↓</span>;
  return <span style={{ color: "var(--text-dim)", fontSize: 12 }}>↔</span>;
}

// ─── Cost bar (engineer) ───────────────────────────────────────────────────────
function CostBar({ breakdown, total }: { breakdown: NonNullable<Agent["cost_breakdown"]>; total: number }) {
  const parts = [
    { label: "LLM",  value: breakdown.llm_tokens,          color: "#f59e0b" },
    { label: "Tools",value: breakdown.tool_calls,           color: "#60a5fa" },
    { label: "Enf",  value: breakdown.enforcement_overhead, color: "#a78bfa" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", height: 4, borderRadius: 2, overflow: "hidden", gap: 1 }}>
        {parts.map((p) => (
          <div
            key={p.label}
            style={{
              flex: p.value / total,
              background: p.color,
              opacity: 0.8,
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {parts.map((p) => (
          <span key={p.label} style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            <span style={{ color: p.color }}>■</span> {p.label}: ${p.value.toFixed(2)}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── AgentCard ─────────────────────────────────────────────────────────────────
export function AgentCard({
  agent,
  complianceStatus = "unknown",
  isRunning = false,
}: {
  agent: Agent;
  complianceStatus?: "pass" | "fail" | "unknown";
  isRunning?: boolean;
}) {
  const { mode } = useMode();
  const [expanded, setExpanded] = useState(false);

  const hasAlert = agent.violations_30d > 0 || agent.tier === "restricted";

  const pendingHref = (cta?: string): string => {
    const text = (cta ?? "").toLowerCase();
    if (text.includes("enforcement") || text.includes("violation")) return `/agents/${agent.id}#enforcement`;
    if (text.includes("contract") || text.includes("approve")) return `/agents/${agent.id}#contracts`;
    return `/agents/${agent.id}`;
  };

  const cardStyle: React.CSSProperties = {
    background: isRunning ? "var(--bg-3)" : "var(--bg-2)",
    border: `1px solid ${isRunning ? "rgba(34,197,94,0.5)" : hasAlert ? "rgba(239,68,68,0.3)" : "var(--border-default)"}`,
    borderRadius: "var(--radius-md)",
    padding: "16px",
    cursor: "pointer",
    transition: "border-color 0.15s ease, background 0.15s ease",
    position: "relative",
    overflow: "hidden",
  };

  return (
    <div
      style={cardStyle}
      onClick={() => setExpanded(!expanded)}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor =
          hasAlert ? "rgba(239,68,68,0.6)" : "var(--border-accent)";
        (e.currentTarget as HTMLDivElement).style.background = "var(--bg-3)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLDivElement).style.borderColor =
          hasAlert ? "rgba(239,68,68,0.3)" : "var(--border-default)";
        (e.currentTarget as HTMLDivElement).style.background = "var(--bg-2)";
      }}
    >
      {/* Running stripe */}
      {isRunning && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: 3,
            height: "100%",
            background: "#22c55e",
            animation: "norma-pulse-bar 1.2s ease-in-out infinite",
          }}
        />
      )}
      {/* Alert stripe */}
      {!isRunning && hasAlert && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: 3,
            height: "100%",
            background: "#ef4444",
          }}
        />
      )}

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10, paddingLeft: hasAlert ? 8 : 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: mode === "vp" ? "14px" : "12px",
                fontWeight: 600,
                color: "var(--text-primary)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {mode === "vp" ? agent.name : agent.id}
            </span>
            {isRunning && (
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "2px 7px",
                  background: "rgba(34,197,94,0.15)",
                  border: "1px solid rgba(34,197,94,0.4)",
                  borderRadius: "var(--radius-sm)",
                  color: "#22c55e",
                  fontSize: "9px",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.1em",
                  fontWeight: 600,
                }}
              >
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    background: "#22c55e",
                    display: "inline-block",
                    animation: "norma-pulse-dot 1s ease-in-out infinite",
                  }}
                />
                RUNNING
              </span>
            )}
            <span
              style={{
                fontSize: "9px",
                padding: "1px 6px",
                borderRadius: "var(--radius-sm)",
                fontFamily: "var(--font-mono)",
                border: "1px solid var(--border-subtle)",
                color:
                  complianceStatus === "pass"
                    ? "var(--green)"
                    : complianceStatus === "fail"
                      ? "var(--red)"
                      : "var(--text-dim)",
                background:
                  complianceStatus === "pass"
                    ? "rgba(34,197,94,0.10)"
                    : complianceStatus === "fail"
                      ? "rgba(239,68,68,0.10)"
                      : "var(--bg-3)",
              }}
            >
              CMP {complianceStatus === "pass" ? "PASS" : complianceStatus === "fail" ? "FAIL" : "—"}
            </span>
          </div>
          {mode === "vp" && (
            <p
              style={{
                fontSize: "11px",
                color: "var(--text-secondary)",
                fontFamily: "var(--font-sans)",
                lineHeight: 1.4,
                fontWeight: 300,
              }}
            >
              {agent.description}
            </p>
          )}
          {mode === "engineer" && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                Contract v{agent.contract_version}
              </span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>|</span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                Deployed: {new Date(agent.contract_deployed).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>|</span>
              <span style={{ fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                Approved by: {agent.approved_by}
              </span>
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0, marginLeft: 12 }}>
          <TierBadge tier={agent.tier} />
          {mode === "engineer" && (
            <span style={{ fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
              score: {agent.trust_score.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* ── VP Stats ────────────────────────────────────────────────── */}
      {mode === "vp" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 10 }}>
          <Stat
            label="Quality"
            value={`${(agent.quality_score * 100).toFixed(0)}%`}
            color={agent.quality_score >= 0.85 ? "var(--green)" : agent.quality_score >= 0.75 ? "var(--amber)" : "var(--red)"}
          />
          <Stat
            label="Cost/task"
            value={`$${agent.cost_per_task.toFixed(2)}`}
          />
          <Stat
            label="Completion"
            value={`${(agent.completion_rate * 100).toFixed(0)}%`}
          />
          <Stat
            label="Trend"
            value=""
          />
        </div>
      )}

      {/* VP second row – trend + sparkline */}
      {mode === "vp" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingTop: 8,
            borderTop: "1px solid var(--border-subtle)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <TrendIndicator dir={agent.trend} />
            <span style={{ fontSize: "11px", color: "var(--text-secondary)", fontFamily: "var(--font-sans)" }}>
              {agent.trend === "up" ? "Improving" : agent.trend === "down" ? "Degrading" : "Stable"}
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              Last reviewed: {new Date(agent.contract_deployed).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            </span>
          </div>
          <TrustSparkline data={agent.trust_history} width={120} height={28} />
        </div>
      )}

      {/* ── Engineer Stats ──────────────────────────────────────────── */}
      {mode === "engineer" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 10 }}>
            <Stat label="Latency P50"  value={`${agent.latency_p50_ms}ms`} />
            <Stat label="Latency P95"  value={`${agent.latency_p95_ms}ms`} />
            <Stat label="Avg tokens"   value={agent.avg_tokens.toLocaleString()} />
            <Stat
              label="Violations 30d"
              value={agent.violations_30d}
              color={agent.violations_30d === 0 ? "var(--green)" : "var(--red)"}
            />
            <Stat label="Quality adj. cost" value={`$${agent.quality_adj_cost.toFixed(3)}`} />
            <Stat label="Trust score" value={agent.trust_score.toFixed(3)} />
          </div>

          <div
            style={{
              paddingTop: 8,
              borderTop: "1px solid var(--border-subtle)",
              marginBottom: 8,
            }}
          >
            <div style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.06em", marginBottom: 4, fontFamily: "var(--font-mono)" }}>
              COST BREAKDOWN
            </div>
            {agent.cost_breakdown && (
              <CostBar breakdown={agent.cost_breakdown} total={agent.cost_per_task} />
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              {`Enforcement: ${agent.violations_30d === 0 ? "0 violations (30d)" : `${agent.violations_30d} violation${agent.violations_30d > 1 ? "s" : ""} (30d)`}`}
            </span>
            <TrustSparkline data={agent.trust_history} width={100} height={24} />
          </div>
        </>
      )}

      {/* ── Pending Action (VP only) ─────────────────────────────────── */}
      {mode === "vp" && agent.pending_action && (
        <div
          style={{
            marginTop: 10,
            padding: "10px 12px",
            background: "rgba(239,68,68,0.06)",
            border: "1px solid rgba(239,68,68,0.2)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <p
            style={{
              fontSize: "11px",
              color: "#fca5a5",
              fontFamily: "var(--font-sans)",
              marginBottom: 8,
              lineHeight: 1.5,
              fontWeight: 300,
            }}
          >
            {agent.pending_action.message}
          </p>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                window.location.href = pendingHref(agent.pending_action?.cta_primary);
              }}
              style={{
                padding: "4px 12px",
                background: "#ef4444",
                color: "#fff",
                border: "none",
                borderRadius: "var(--radius-sm)",
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.06em",
                cursor: "pointer",
                textTransform: "uppercase",
              }}
            >
              {agent.pending_action.cta_primary}
            </button>
            {agent.pending_action.cta_secondary && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  window.location.href = pendingHref(agent.pending_action?.cta_secondary);
                }}
                style={{
                  padding: "4px 12px",
                  background: "transparent",
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  fontSize: "10px",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.06em",
                  cursor: "pointer",
                  textTransform: "uppercase",
                }}
              >
                {agent.pending_action.cta_secondary}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Expanded detail (engineer) ─────────────────────────────── */}
      {mode === "engineer" && expanded && (
        <div
          style={{
            marginTop: 10,
            padding: "10px 12px",
            background: "var(--bg-1)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            color: "var(--text-secondary)",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span style={{ color: "var(--text-dim)", fontSize: "10px" }}>LAST RUN AT</span>
          <span>{new Date(agent.last_run_at).toLocaleString()}</span>
          <div style={{ marginTop: 4 }}>
            <span style={{ color: "var(--text-dim)", fontSize: "10px" }}>PENDING_CONTRACT_VERSION</span>
            <span style={{ display: "block" }}>
              {agent.tier === "restricted" ? `v${(parseFloat(agent.contract_version) + 0.1).toFixed(1)} awaiting human approval` : "—"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
