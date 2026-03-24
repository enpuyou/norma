"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getAgents, getCompliancePosture } from "@/lib/api";
import type { Agent, Tier } from "@/lib/types";
import { AgentCard } from "@/components/AgentCard";
import { ModeToggle } from "@/components/ModeToggle";

// ─── Tier pill ─────────────────────────────────────────────────────────────────
const TIER: Record<Tier, { color: string; bg: string; border: string }> = {
  restricted: { color: "#ef4444", bg: "rgba(239,68,68,0.10)", border: "rgba(239,68,68,0.25)" },
  standard:   { color: "#60a5fa", bg: "rgba(96,165,250,0.10)", border: "rgba(96,165,250,0.25)" },
  trusted:    { color: "#22c55e", bg: "rgba(34,197,94,0.10)", border: "rgba(34,197,94,0.25)" },
};

function TierPill({ tier }: { tier: Tier }) {
  const t = TIER[tier];
  return (
    <span style={{
      padding: "1px 7px",
      background: t.bg,
      border: `1px solid ${t.border}`,
      borderRadius: "var(--radius-sm)",
      color: t.color,
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      letterSpacing: "0.08em",
      textTransform: "uppercase",
    }}>
      {tier}
    </span>
  );
}

function fmtDate(ts: string | null) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
      hour12: false,
    });
  } catch { return ts; }
}

// ─── List row ──────────────────────────────────────────────────────────────────
function AgentRow({ agent, onClick }: { agent: Agent; onClick: () => void }) {
  const qualityColor =
    agent.quality_score >= 0.85 ? "var(--green)" :
    agent.quality_score >= 0.70 ? "var(--amber)" : "var(--red)";
  const trustColor =
    Number(agent.trust_score) >= 0.80 ? "var(--green)" :
    Number(agent.trust_score) >= 0.50 ? "var(--amber)" : "var(--red)";

  return (
    <tr
      onClick={onClick}
      style={{ borderTop: "1px solid var(--border-subtle)", cursor: "pointer" }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-2)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <td style={{ padding: "10px 14px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: "12px", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
            {agent.id}
          </span>
          <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-sans)", fontWeight: 300 }}>
            {agent.name}
          </span>
        </div>
      </td>
      <td style={{ padding: "10px 14px" }}>
        <TierPill tier={agent.tier} />
      </td>
      <td style={{ padding: "10px 14px", fontFamily: "var(--font-mono)", fontSize: "12px", color: trustColor }}>
        {(Number(agent.trust_score) * 100).toFixed(0)}%
      </td>
      <td style={{ padding: "10px 14px", fontFamily: "var(--font-mono)", fontSize: "12px", color: qualityColor }}>
        {(agent.quality_score * 100).toFixed(0)}%
      </td>
      <td style={{ padding: "10px 14px", fontFamily: "var(--font-mono)", fontSize: "12px", color: agent.violations_30d > 0 ? "var(--red)" : "var(--text-dim)" }}>
        {agent.violations_30d}
      </td>
      <td style={{ padding: "10px 14px", fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
        {fmtDate(agent.last_run_at)}
      </td>
    </tr>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────────
export default function AgentsRegistryPage() {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [complianceMap, setComplianceMap] = useState<Record<string, "pass" | "fail" | "unknown">>({});
  const [topologyView, setTopologyView] = useState<"layout" | "structure">("layout");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [tierFilter, setTierFilter] = useState<string>("");
  const [sortBy, setSortBy] = useState<"last_run" | "trust" | "quality" | "violations">("last_run");
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set());

  useEffect(() => {
    getAgents().then(async (ag) => {
      setAgents(ag);
      const statuses = await Promise.all(ag.map(async (a) => {
        const posture = await getCompliancePosture(a.id);
        return {
          id: a.id,
          status: posture?.passed === true ? "pass" : posture?.passed === false ? "fail" : "unknown",
        };
      }));
      const map: Record<string, "pass" | "fail" | "unknown"> = {};
      for (const s of statuses) map[s.id] = s.status as "pass" | "fail" | "unknown";
      setComplianceMap(map);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const filtered = agents
    .filter((a) => !tierFilter || a.tier === tierFilter)
    .sort((a, b) => {
      if (sortBy === "last_run") {
        const ta = a.last_run_at ? new Date(a.last_run_at).getTime() : 0;
        const tb = b.last_run_at ? new Date(b.last_run_at).getTime() : 0;
        return tb - ta;
      }
      if (sortBy === "trust") return Number(b.trust_score) - Number(a.trust_score);
      if (sortBy === "quality") return b.quality_score - a.quality_score;
      if (sortBy === "violations") return b.violations_30d - a.violations_30d;
      return 0;
    });

  const topLevelAgents = filtered.filter((a) => !a.parent_agent_id);

  const toggleParent = (agentId: string) => {
    setExpandedParents((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  };

  const selectStyle: React.CSSProperties = {
    padding: "4px 8px",
    background: "var(--bg-2)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-sm)",
    color: "var(--text-secondary)",
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    cursor: "pointer",
  };

  const iconBtnStyle = (active: boolean): React.CSSProperties => ({
    padding: "4px 8px",
    background: active ? "var(--amber-glow)" : "var(--bg-2)",
    border: `1px solid ${active ? "rgba(245,158,11,0.3)" : "var(--border-default)"}`,
    borderRadius: "var(--radius-sm)",
    color: active ? "var(--amber)" : "var(--text-dim)",
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    cursor: "pointer",
    lineHeight: 1,
  });

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-0)", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>

      {/* ── Header ─────────────────────────────────────────────────── */}
      <header style={{
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
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link
            href="/"
            style={{
              fontSize: "15px",
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--amber)",
              textDecoration: "none",
              fontFamily: "var(--font-mono)",
            }}
          >
            NORMA
          </Link>
          <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
            / <Link href="/" style={{ color: "var(--text-dim)", textDecoration: "none" }}>dashboard</Link> / registry
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontSize: "11px",
            fontWeight: 600,
            color: "var(--text-primary)",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}>
            REGISTRY
          </span>
          <span style={{
            fontSize: "11px",
            padding: "1px 7px",
            background: "var(--amber-glow)",
            border: "1px solid rgba(245,158,11,0.2)",
            borderRadius: "var(--radius-sm)",
            color: "var(--amber)",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.08em",
          }}>
            {filtered.length}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <ModeToggle />
        </div>
      </header>

      {/* ── Main ────────────────────────────────────────────────────── */}
      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Filter + view toggle bar */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Tier filter */}
          <select
            value={tierFilter}
            onChange={(e) => setTierFilter(e.target.value)}
            style={selectStyle}
          >
            <option value="">All tiers</option>
            <option value="trusted">Trusted</option>
            <option value="standard">Standard</option>
            <option value="restricted">Restricted</option>
          </select>

          {/* Sort */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            style={selectStyle}
          >
            <option value="last_run">Sort: Last Run</option>
            <option value="trust">Sort: Trust</option>
            <option value="quality">Sort: Quality</option>
            <option value="violations">Sort: Violations</option>
          </select>

          <div style={{ flex: 1 }} />

          <div style={{ display: "inline-flex", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
            <button
              onClick={() => setTopologyView("layout")}
              style={{
                padding: "4px 8px",
                border: "none",
                borderRight: "1px solid var(--border-default)",
                background: topologyView === "layout" ? "var(--amber-glow)" : "transparent",
                color: topologyView === "layout" ? "var(--amber)" : "var(--text-dim)",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                letterSpacing: "0.06em",
                cursor: "pointer",
              }}
            >
              LAYOUT
            </button>
            <button
              onClick={() => setTopologyView("structure")}
              style={{
                padding: "4px 8px",
                border: "none",
                background: topologyView === "structure" ? "var(--amber-glow)" : "transparent",
                color: topologyView === "structure" ? "var(--amber)" : "var(--text-dim)",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                letterSpacing: "0.06em",
                cursor: "pointer",
              }}
            >
              STRUCTURE
            </button>
          </div>

          {/* View toggle */}
          <button
            onClick={() => setViewMode("grid")}
            title="Grid view"
            style={iconBtnStyle(viewMode === "grid")}
            disabled={topologyView !== "layout"}
          >
            ⊞
          </button>
          <button
            onClick={() => setViewMode("list")}
            title="List view"
            style={iconBtnStyle(viewMode === "list")}
            disabled={topologyView !== "layout"}
          >
            ≡
          </button>
        </div>

        {topologyView === "structure" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {topLevelAgents.length === 0 ? (
              <div style={{ padding: "24px 14px", textAlign: "center", fontSize: "11px", color: "var(--text-dim)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", background: "var(--bg-2)" }}>
                No top-level agents match the current filter.
              </div>
            ) : (
              topLevelAgents.map((agent) => {
                const hasSubs = agent.sub_agents && agent.sub_agents.length > 0;
                const open = expandedParents.has(agent.id);
                return (
                  <div key={agent.id} style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", background: "var(--bg-2)", overflow: "hidden" }}>
                    <div style={{ padding: "10px 12px", display: "flex", alignItems: "center", gap: 8, borderBottom: open ? "1px solid var(--border-subtle)" : "none" }}>
                      <button
                        onClick={() => router.push(`/agents/${agent.id}`)}
                        style={{ all: "unset", cursor: "pointer", fontSize: 11, color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}
                      >
                        {agent.id}
                      </button>
                      <span style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>{agent.type}</span>
                      <span style={{ fontSize: 9, color: "var(--text-dim)", marginLeft: "auto", fontFamily: "var(--font-mono)" }}>{agent.sub_agents?.length ?? 0} sub-agent{(agent.sub_agents?.length ?? 0) !== 1 ? "s" : ""}</span>
                      {hasSubs && (
                        <button
                          onClick={() => toggleParent(agent.id)}
                          style={{ padding: "2px 8px", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", background: "transparent", color: "var(--text-dim)", fontFamily: "var(--font-mono)", fontSize: 9, cursor: "pointer" }}
                        >
                          {open ? "HIDE" : "UNFOLD"}
                        </button>
                      )}
                    </div>
                    {hasSubs && open && (
                      <div style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6, background: "var(--bg-1)" }}>
                        {agent.sub_agents.map((sub) => (
                          <button
                            key={sub.agent_id}
                            onClick={() => router.push(`/agents/${sub.agent_id}`)}
                            style={{
                              all: "unset",
                              cursor: "pointer",
                              padding: "6px 8px",
                              border: "1px solid var(--border-subtle)",
                              borderRadius: "var(--radius-sm)",
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              fontFamily: "var(--font-mono)",
                              fontSize: 12,
                              color: "var(--text-secondary)",
                              background: "var(--bg-2)",
                            }}
                          >
                            <span>{sub.agent_id}</span>
                            <span style={{ color: "var(--text-dim)" }}>{(sub.trust_score * 100).toFixed(0)}%</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* Grid view */}
        {topologyView === "layout" && viewMode === "grid" && (
          filtered.length === 0 && !loading ? (
            <div style={{
              padding: "48px 24px",
              textAlign: "center",
              background: "var(--bg-1)",
              border: "1px dashed var(--border-default)",
              borderRadius: "var(--radius-sm)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 12,
            }}>
              <span style={{ fontSize: "24px", opacity: 0.3 }}>◎</span>
              <span style={{ fontSize: "12px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
                {tierFilter ? `No ${tierFilter} agents found.` : "No agents registered yet."}
              </span>
            </div>
          ) : (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))",
            gap: 10,
          }}>
            {filtered.map((agent) => (
              <div
                key={agent.id}
                onClick={() => router.push(`/agents/${agent.id}`)}
                style={{ cursor: "pointer" }}
              >
                <AgentCard agent={agent} complianceStatus={complianceMap[agent.id] ?? "unknown"} />
              </div>
            ))}
          </div>
          )
        )}

        {/* List view */}
        {topologyView === "layout" && viewMode === "list" && (
          <div style={{
            background: "var(--bg-2)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            overflow: "hidden",
          }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
              <thead>
                <tr style={{ background: "var(--bg-1)" }}>
                  {["AGENT", "TIER", "TRUST", "QUALITY", "VIOLATIONS 30D", "LAST RUN"].map((h) => (
                    <th key={h} style={{
                      padding: "7px 14px",
                      textAlign: "left",
                      fontSize: "11px",
                      color: "var(--text-dim)",
                      fontWeight: 400,
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      whiteSpace: "nowrap",
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((agent) => (
                  <AgentRow
                    key={agent.id}
                    agent={agent}
                    onClick={() => router.push(`/agents/${agent.id}`)}
                  />
                ))}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div style={{ padding: "24px 14px", textAlign: "center", fontSize: "11px", color: "var(--text-dim)" }}>
                No agents match the current filter.
              </div>
            )}
          </div>
        )}

        {topologyView === "layout" && filtered.length === 0 && viewMode === "grid" && (
          <div style={{
            padding: "48px 0",
            textAlign: "center",
            fontSize: "12px",
            color: "var(--text-dim)",
          }}>
            No agents match the current filter.
          </div>
        )}
      </main>
    </div>
  );
}
