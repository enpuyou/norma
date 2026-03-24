"use client";

import { useEffect, useState } from "react";
import { getRecommendations, getAnomalies, approveContract, type Recommendation, type Anomaly } from "@/lib/api";

const PRIORITY_COLORS: Record<string, string> = {
  high:   "var(--red)",
  medium: "var(--amber)",
  low:    "var(--blue)",
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "var(--red)",
  warning:  "var(--amber)",
};

function chipStyle(color: string) {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "1px 7px",
    background: `${color}18`,
    color,
    border: `1px solid ${color}30`,
    borderRadius: "var(--radius-sm)",
    fontSize: "10px",
    fontFamily: "var(--font-mono)",
    letterSpacing: "0.04em",
    textTransform: "uppercase" as const,
  };
}

interface Props {
  agentId: string;
}

export function RecommendationBanner({ agentId }: Props) {
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState<string | null>(null);
  const [approvedVersions, setApprovedVersions] = useState<Set<string>>(new Set());

  useEffect(() => {
    setLoading(true);
    Promise.all([getRecommendations(agentId), getAnomalies(agentId)])
      .then(([r, a]) => {
        setRecs(r);
        setAnomalies(a);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [agentId]);

  async function handleApproveContract(r: Recommendation) {
    const version = r.contract_version ?? "1.0";
    const approver = window.prompt("Your name (recorded as approver):", "admin");
    if (!approver) return;
    setApproving(version);
    try {
      await approveContract(agentId, version, approver);
      setApprovedVersions((prev) => new Set(prev).add(version));
      setRecs((prev) => prev.filter((x) => x.action !== "approve_contract_proposal" || (x.contract_version ?? "1.0") !== version));
    } catch (err) {
      alert(`Failed to approve contract: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setApproving(null);
    }
  }

  if (loading || (recs.length === 0 && anomalies.length === 0)) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        margin: "12px 0",
      }}
    >
      {/* Anomalies */}
      {anomalies.map((a, i) => (
        <div
          key={`anom-${i}`}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "10px 14px",
            background: `${SEVERITY_COLORS[a.severity] ?? "var(--amber)"}0c`,
            border: `1px solid ${SEVERITY_COLORS[a.severity] ?? "var(--amber)"}30`,
            borderRadius: "var(--radius-sm)",
          }}
        >
          <span style={{ fontSize: "14px", lineHeight: 1, marginTop: 1 }}>
            {a.severity === "critical" ? "🔴" : "🟡"}
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
              <span style={chipStyle(SEVERITY_COLORS[a.severity] ?? "var(--amber)")}>
                {a.type.replace("_", " ")}
              </span>
              {a.change_pct !== null && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: SEVERITY_COLORS[a.severity] ?? "var(--amber)", fontWeight: 600 }}>
                  {a.change_pct > 0 ? "+" : ""}{a.change_pct}%
                </span>
              )}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>
                {a.metric} · {a.window}
              </span>
            </div>
            <p style={{ margin: 0, fontSize: "12px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
              {a.message}
            </p>
          </div>
        </div>
      ))}

      {/* Recommendations */}
      {recs.map((r, i) => {
        const color = PRIORITY_COLORS[r.priority] ?? "var(--blue)";
        return (
          <div
            key={`rec-${i}`}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
              padding: "10px 14px",
              background: `${color}0c`,
              border: `1px solid ${color}30`,
              borderRadius: "var(--radius-sm)",
            }}
          >
            <span style={{ fontSize: "14px", lineHeight: 1, marginTop: 1 }}>💡</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
                <span style={chipStyle(color)}>{r.priority}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-primary)", fontWeight: 600 }}>
                  {r.title}
                </span>
              </div>
              <p style={{ margin: "0 0 5px", fontSize: "11px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
                {r.evidence}
              </p>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                  confidence: {r.confidence} · sources: {r.data_sources.join(", ")}
                </span>
                <button
                  disabled={r.action === "approve_contract_proposal" && approving !== null}
                  style={{
                    padding: "2px 10px",
                    background: r.action === "approve_contract_proposal" && approvedVersions.has(r.contract_version ?? "1.0") ? "var(--green)22" : `${color}22`,
                    color: r.action === "approve_contract_proposal" && approvedVersions.has(r.contract_version ?? "1.0") ? "var(--green)" : color,
                    border: `1px solid ${color}40`,
                    borderRadius: "var(--radius-sm)",
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    cursor: r.action === "approve_contract_proposal" ? "pointer" : "default",
                    letterSpacing: "0.04em",
                    opacity: r.action === "approve_contract_proposal" && approving !== null ? 0.5 : 1,
                  }}
                  onClick={() => {
                    if (r.action === "approve_contract_proposal") {
                      handleApproveContract(r);
                    }
                  }}
                >
                  {r.action === "approve_contract_proposal" && approving === (r.contract_version ?? "1.0")
                    ? "Approving…"
                    : r.cta}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
