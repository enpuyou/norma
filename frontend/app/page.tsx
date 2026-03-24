"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { Agent, Alert } from "@/lib/types";
import { bulkCheckAgentChanges, bulkPauseAgents, getAgents, getAlerts, getCompliancePosture, getFleetExportUrl } from "@/lib/api";
import { AgentCard } from "@/components/AgentCard";
import { AlertBanner } from "@/components/AlertBanner";
import { ModeToggle } from "@/components/ModeToggle";
import { QAPanel } from "@/components/QAPanel";
import { RunTimeline } from "@/components/RunTimeline";
import { OnboardAgentModal } from "@/components/OnboardAgentModal";
import { GovernanceReports } from "@/components/GovernanceReports";
import { useEventStream } from "@/hooks/useEventStream";
import { useMode } from "@/hooks/useMode";

// ── Fleet summary bar ──────────────────────────────────────────────────────────
function FleetSummary({ agents }: { agents: Agent[] }) {
  const trusted = agents.filter((a) => a.tier === "trusted").length;
  const standard = agents.filter((a) => a.tier === "standard").length;
  const restricted = agents.filter((a) => a.tier === "restricted").length;
  const avgQuality = agents.length ? agents.reduce((s, a) => s + a.quality_score, 0) / agents.length : 0;
  const totalCost = agents.reduce((s, a) => s + a.cost_per_task, 0);
  const violations = agents.reduce((s, a) => s + a.violations_30d, 0);

  const items = [
    { label: "AGENTS", value: agents.length.toString(), color: "var(--text-primary)" },
    { label: "TRUSTED", value: trusted.toString(), color: "var(--green)" },
    { label: "STANDARD", value: standard.toString(), color: "var(--blue)" },
    { label: "RESTRICTED", value: restricted.toString(), color: "var(--red)" },
    { label: "AVG QUALITY", value: `${(avgQuality * 100).toFixed(0)}%`, color: avgQuality >= 0.85 ? "var(--green)" : "var(--amber)" },
    { label: "TOTAL COST/TASK", value: `$${totalCost.toFixed(2)}`, color: "var(--text-primary)" },
    { label: "VIOLATIONS 30D", value: violations.toString(), color: violations > 0 ? "var(--red)" : "var(--green)" },
  ];

  return (
    <div
      style={{
        display: "flex",
        gap: 0,
        background: "var(--bg-1)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-sm)",
        overflow: "hidden",
        fontFamily: "var(--font-mono)",
        flexWrap: "wrap",
      }}
    >
      {items.map((item, i) => (
        <div
          key={item.label}
          style={{
            padding: "8px 16px",
            borderRight: i < items.length - 1 ? "1px solid var(--border-subtle)" : "none",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
            {item.label}
          </span>
          <span style={{ fontSize: "16px", fontWeight: 600, color: item.color, lineHeight: 1 }}>
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const { mode } = useMode();
  const router = useRouter();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [isLive, setIsLive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [complianceMap, setComplianceMap] = useState<Record<string, "pass" | "fail" | "unknown">>({});
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [topologyView, setTopologyView] = useState<"layout" | "structure">("layout");
  const [fleetView, setFleetView] = useState<"grid" | "list">("grid");
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set());
  const [onboardOpen, setOnboardOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [runningAgents, setRunningAgents] = useState<Set<string>>(new Set());
  const [dismissedAlertIds, setDismissedAlertIds] = useState<Set<string>>(() => {
    try {
      if (typeof window === "undefined") return new Set();
      const stored = localStorage.getItem("norma_dismissed_alerts");
      return stored ? new Set(JSON.parse(stored) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });

  const handleDismissAlert = (id: string | number) => {
    const key = String(id);
    setDismissedAlertIds((prev) => {
      const next = new Set(prev);
      next.add(key);
      try { localStorage.setItem("norma_dismissed_alerts", JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  };

  const visibleAlerts = alerts.filter((a) => !dismissedAlertIds.has(String(a.id)));

  // Deduplicate dashboard alerts by (agent_id + metric)
  const dedupedAlerts = visibleAlerts.reduce((acc, alert) => {
    const key = `${alert.agent_id}::${alert.metric}`;
    const existing = acc.get(key);
    if (!existing) {
      acc.set(key, { alert, count: 1 });
    } else {
      const existingTs = new Date(existing.alert.timestamp).getTime();
      const thisTs = new Date(alert.timestamp).getTime();
      acc.set(key, {
        alert: thisTs > existingTs ? alert : existing.alert,
        count: existing.count + 1,
      });
    }
    return acc;
  }, new Map<string, { alert: Alert; count: number }>());
  const dedupedVisibleAlerts = [...dedupedAlerts.values()];

  // SSE real-time updates — refresh agents on any run_completed or agent_created
  const { lastEvent } = useEventStream();
  useEffect(() => {
    if (lastEvent?.type === "run_started") {
      const agentId = (lastEvent.data as { agent_id?: string })?.agent_id;
      if (agentId) {
        setRunningAgents((prev) => { const next = new Set(prev); next.add(agentId); return next; });
      }
      return;
    }
    if (lastEvent?.type === "run_completed") {
      const agentId = (lastEvent.data as { agent_id?: string })?.agent_id;
      if (agentId) {
        setRunningAgents((prev) => { const next = new Set(prev); next.delete(agentId); return next; });
      }
    }
    if (lastEvent?.type === "run_completed" || lastEvent?.type === "agent_created" || lastEvent?.type === "trust_changed") {
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
      }).catch(() => { });
    }
  }, [lastEvent]);

  useEffect(() => {
    Promise.all([
      getAgents(),
      getAlerts(),
    ]).then(async ([ag, al]) => {
      setAgents(ag);
      setAlerts(al);
      const statuses = await Promise.all(ag.map(async (a) => ({
        id: a.id,
        posture: await getCompliancePosture(a.id),
      })));
      const map: Record<string, "pass" | "fail" | "unknown"> = {};
      for (const s of statuses) {
        map[s.id] = s.posture?.passed === true ? "pass" : s.posture?.passed === false ? "fail" : "unknown";
      }
      setComplianceMap(map);
      setIsLive(true);
      setLoading(false);
    }).catch(() => {
      setLoading(false);
    });
  }, []);

  const now = new Date();
  const clock = now.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  const runBulkPause = async (enabled: boolean) => {
    setBulkBusy(true);
    setBulkMsg(null);
    try {
      const res = await bulkPauseAgents(enabled);
      setBulkMsg(`${enabled ? "Resumed" : "Paused"} ${res.updated} agent${res.updated !== 1 ? "s" : ""}`);
      const ag = await getAgents();
      setAgents(ag);
    } catch (err) {
      setBulkMsg(err instanceof Error ? err.message : "Bulk update failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const runBulkScan = async () => {
    setBulkBusy(true);
    setBulkMsg(null);
    try {
      const res = await bulkCheckAgentChanges();
      setBulkMsg(`Scanned ${res.scanned} agent${res.scanned !== 1 ? "s" : ""} · ${res.changed} changed`);
      const ag = await getAgents();
      setAgents(ag);
    } catch (err) {
      setBulkMsg(err instanceof Error ? err.message : "Bulk scan failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const recentAgents = [...agents]
    .sort((a, b) => {
      const ta = a.last_run_at ? new Date(a.last_run_at).getTime() : 0;
      const tb = b.last_run_at ? new Date(b.last_run_at).getTime() : 0;
      return tb - ta;
    })
    .slice(0, 9);

  const topLevelRecentAgents = recentAgents.filter((agent) => !agent.parent_agent_id);

  const toggleParent = (agentId: string) => {
    setExpandedParents((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
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
      {/* Onboard Agent Modal */}
      <OnboardAgentModal
        open={onboardOpen}
        onClose={() => setOnboardOpen(false)}
        onCreated={(agent) => {
          setAgents((prev) => {
            // Update or add agent
            const idx = prev.findIndex((a) => a.id === agent.id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = agent;
              return updated;
            }
            return [...prev, agent];
          });
        }}
      />

      {/* ── Topbar ────────────────────────────────────────────────── */}
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
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
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
          <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
            / agent governance
          </span>
        </div>

        {/* Center nav */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {[
            { label: "DASHBOARD", href: "/", active: true },
            { label: "REGISTRY", href: "/agents", active: false },
            { label: "LOG", href: "/runs", active: false },
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
                transition: "all 0.12s ease",
              }}
              onMouseEnter={(e) => {
                if (!item.active) {
                  e.currentTarget.style.borderColor = "var(--border-default)";
                  e.currentTarget.style.color = "var(--text-secondary)";
                }
              }}
              onMouseLeave={(e) => {
                if (!item.active) {
                  e.currentTarget.style.borderColor = "var(--border-subtle)";
                  e.currentTarget.style.color = "var(--text-dim)";
                }
              }}
            >
              {item.label}
            </Link>
          ))}
        </div>

        {/* Right */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            {clock}
          </span>
          <div style={{ width: 1, height: 20, background: "var(--border-default)" }} />
          <span style={{
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            padding: "2px 6px",
            borderRadius: "var(--radius-sm)",
            background: isLive ? "rgba(52,211,153,0.1)" : "rgba(156,163,175,0.1)",
            color: isLive ? "var(--green)" : "var(--text-dim)",
            border: `1px solid ${isLive ? "rgba(52,211,153,0.2)" : "rgba(156,163,175,0.15)"}`,
            letterSpacing: "0.06em",
          }}>
            {isLive ? "● LIVE" : "○ LOADING"}
          </span>
          <ModeToggle />
        </div>
      </header>

      {/* ── Main content ──────────────────────────────────────────── */}
      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Fleet summary strip */}
        <FleetSummary agents={agents} />

        {/* Section heading */}
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: "18px", fontWeight: 600, color: "var(--text-primary)", letterSpacing: "0.02em" }}>
              Fleet View
            </span>
            <span
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                background: "var(--amber-glow)",
                border: "1px solid rgba(245,158,11,0.2)",
                borderRadius: "var(--radius-sm)",
                color: "var(--amber)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              {mode === "vp" ? "Manage View" : "Dev View"}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ display: "inline-flex", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
              <button
                onClick={() => setTopologyView("layout")}
                style={{
                  padding: "4px 8px",
                  background: topologyView === "layout" ? "var(--amber-glow)" : "transparent",
                  color: topologyView === "layout" ? "var(--amber)" : "var(--text-dim)",
                  border: "none",
                  borderRight: "1px solid var(--border-default)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                }}
              >
                LAYOUT
              </button>
              <button
                onClick={() => setTopologyView("structure")}
                style={{
                  padding: "4px 8px",
                  background: topologyView === "structure" ? "var(--amber-glow)" : "transparent",
                  color: topologyView === "structure" ? "var(--amber)" : "var(--text-dim)",
                  border: "none",
                  borderRight: "1px solid var(--border-default)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                }}
              >
                STRUCTURE
              </button>
              <button
                onClick={() => setFleetView("grid")}
                disabled={topologyView !== "layout"}
                style={{
                  padding: "4px 8px",
                  background: fleetView === "grid" ? "var(--amber-glow)" : "transparent",
                  color: fleetView === "grid" ? "var(--amber)" : "var(--text-dim)",
                  border: "none",
                  borderRight: "1px solid var(--border-default)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                }}
              >
                GRID
              </button>
              <button
                onClick={() => setFleetView("list")}
                disabled={topologyView !== "layout"}
                style={{
                  padding: "4px 8px",
                  background: fleetView === "list" ? "var(--amber-glow)" : "transparent",
                  color: fleetView === "list" ? "var(--amber)" : "var(--text-dim)",
                  border: "none",
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                }}
              >
                LIST
              </button>
            </div>
            <button
              onClick={() => setOnboardOpen(true)}
              style={{
                padding: "6px 14px",
                background: "var(--amber)",
                border: "none",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-inverse)",
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                fontWeight: 600,
                cursor: "pointer",
                letterSpacing: "0.04em",
              }}
            >
              + Onboard Agent
            </button>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => runBulkPause(false)}
            disabled={bulkBusy}
            style={{ padding: "4px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: 12, fontFamily: "var(--font-mono)", cursor: bulkBusy ? "wait" : "pointer", letterSpacing: "0.06em" }}
          >
            PAUSE FLEET
          </button>
          <button
            onClick={() => runBulkPause(true)}
            disabled={bulkBusy}
            style={{ padding: "4px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: 12, fontFamily: "var(--font-mono)", cursor: bulkBusy ? "wait" : "pointer", letterSpacing: "0.06em" }}
          >
            RESUME FLEET
          </button>
          <button
            onClick={runBulkScan}
            disabled={bulkBusy}
            style={{ padding: "4px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: 12, fontFamily: "var(--font-mono)", cursor: bulkBusy ? "wait" : "pointer", letterSpacing: "0.06em" }}
          >
            SCAN FLEET
          </button>
          <a
            href={getFleetExportUrl()}
            target="_blank"
            rel="noreferrer"
            style={{ padding: "4px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: 12, fontFamily: "var(--font-mono)", letterSpacing: "0.06em", textDecoration: "none" }}
          >
            EXPORT FLEET CSV
          </a>
          {bulkMsg && (
            <span style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginLeft: 4 }}>{bulkMsg}</span>
          )}
        </div>

        <p style={{ fontSize: "12px", color: "var(--text-secondary)", fontFamily: "var(--font-sans)", fontWeight: 300, marginTop: -8 }}>
          {mode === "vp"
            ? "Business summary: cost per task, quality, compliance posture, and actionable decisions."
            : "Technical detail: trust scores, enforcement logs, token flow, and contract diffs."}
          {selectedAgentId && (
            <span style={{ marginLeft: 10, fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--amber)", opacity: 0.85 }}>
              · <span style={{ cursor: "pointer" }} onClick={() => router.push(`/agents/${selectedAgentId}`)}>
                inspecting: {selectedAgentId} →
              </span>
              <button
                onClick={() => setSelectedAgentId(null)}
                style={{ all: "unset", cursor: "pointer", marginLeft: 6, color: "var(--text-dim)", fontSize: "10px" }}
              >
                ✕
              </button>
            </span>
          )}
        </p>

        {/* Active alerts */}
        {dedupedVisibleAlerts.length > 0 && (
          <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
                Active Alerts
                <span style={{
                  marginLeft: 6,
                  padding: "1px 6px",
                  background: "rgba(239,68,68,0.1)",
                  border: "1px solid rgba(239,68,68,0.2)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--red)",
                  fontSize: 9,
                }}>
                  {dedupedVisibleAlerts.length}
                </span>
              </span>
              <Link
                href="/alerts"
                style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)", textDecoration: "none", letterSpacing: "0.04em" }}
              >
                View all →
              </Link>
            </div>
            {dedupedVisibleAlerts.slice(0, 3).map(({ alert: a, count: freq }) => (
              <AlertBanner key={a.id} alert={a} onDismiss={() => handleDismissAlert(a.id)} frequency={freq} />
            ))}
            {dedupedVisibleAlerts.length > 3 && (
              <Link
                href="/alerts"
                style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)", textDecoration: "none", letterSpacing: "0.04em", textAlign: "center", padding: "4px 0" }}
              >
                +{dedupedVisibleAlerts.length - 3} more → View all alerts
              </Link>
            )}
          </section>
        )}

        {/* Agent cards grid */}
        <section>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
              Recent Agents
            </span>
            <Link
              href="/agents"
              style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-dim)", textDecoration: "none", letterSpacing: "0.04em" }}
            >
              View all {agents.length} agents →
            </Link>
          </div>

          {!loading && agents.length === 0 ? (
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
                No agents registered yet.
              </span>
              <button
                onClick={() => setOnboardOpen(true)}
                style={{
                  padding: "6px 16px",
                  background: "var(--amber)",
                  border: "none",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-inverse)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  fontWeight: 600,
                  cursor: "pointer",
                  letterSpacing: "0.04em",
                }}
              >
                + Onboard Agent
              </button>
            </div>
          ) : (
            topologyView === "structure" ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {topLevelRecentAgents.length === 0 ? (
                  <div style={{ padding: "24px 14px", textAlign: "center", fontSize: "11px", color: "var(--text-dim)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", background: "var(--bg-2)" }}>
                    No top-level agents available.
                  </div>
                ) : (
                  topLevelRecentAgents.map((agent) => {
                    const hasSubs = agent.sub_agents && agent.sub_agents.length > 0;
                    const open = expandedParents.has(agent.id);
                    return (
                      <div key={agent.id} style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", background: "var(--bg-2)", overflow: "hidden" }}>
                        <div style={{ padding: "10px 12px", display: "flex", alignItems: "center", gap: 8, borderBottom: open ? "1px solid var(--border-subtle)" : "none" }}>
                          <button onClick={() => router.push(`/agents/${agent.id}`)} style={{ all: "unset", cursor: "pointer", fontSize: 11, color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
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
            ) : fleetView === "grid" ? (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))",
                  gap: 10,
                }}
                className="stagger"
              >
                {recentAgents.map((agent) => (
                  <div
                    key={agent.id}
                    className="animate-fade"
                    onClick={() => router.push(`/agents/${agent.id}`)}
                    style={{ cursor: "pointer" }}
                  >
                    <AgentCard agent={agent} complianceStatus={complianceMap[agent.id] ?? "unknown"} isRunning={runningAgents.has(agent.id)} />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-1)" }}>
                      {["Agent", "Tier", "Trust", "Quality", "Violations", "Last Run"].map((h) => (
                        <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.07em", fontWeight: 500 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {recentAgents.map((agent) => (
                      <tr
                        key={agent.id}
                        onClick={() => router.push(`/agents/${agent.id}`)}
                        style={{ cursor: "pointer", borderTop: "1px solid var(--border-subtle)" }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = "var(--bg-3)"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = "transparent"; }}
                      >
                        <td style={{ padding: "8px 10px", color: "var(--text-primary)" }}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                            {runningAgents.has(agent.id) && (
                              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", display: "inline-block", animation: "norma-pulse-dot 1s ease-in-out infinite", flexShrink: 0 }} />
                            )}
                            {agent.id}
                          </span>
                        </td>
                        <td style={{ padding: "8px 10px", color: "var(--text-dim)", textTransform: "uppercase" }}>{agent.tier}</td>
                        <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>{(Number(agent.trust_score) * 100).toFixed(0)}%</td>
                        <td style={{ padding: "8px 10px", color: "var(--text-secondary)" }}>{(agent.quality_score * 100).toFixed(0)}%</td>
                        <td style={{ padding: "8px 10px", color: agent.violations_30d > 0 ? "var(--red)" : "var(--text-dim)" }}>{agent.violations_30d}</td>
                        <td style={{ padding: "8px 10px", color: "var(--text-dim)" }}>{agent.last_run_at ? new Date(agent.last_run_at).toLocaleString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </section>

        {/* Run timeline — shown when an agent is clicked in either mode */}
        {selectedAgentId && (
          <RunTimeline agentId={selectedAgentId} limit={20} />
        )}

        {/* Q&A panel */}
        <QAPanel agentId={selectedAgentId ?? undefined} />

        {/* Sentinel Governance Reports */}
        <GovernanceReports />

        {/* Footer */}
        <footer
          style={{
            marginTop: 24,
            paddingTop: 16,
            borderTop: "1px solid var(--border-subtle)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            norma.ai — agent governance platform — v0.1.0-alpha
          </span>
          <div style={{ display: "flex", gap: 16 }}>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              backend: <span style={{ color: "var(--amber)" }}>localhost:8080</span>
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              db: <span style={{ color: "var(--blue)" }}>sqlite</span>
            </span>
          </div>
        </footer>
      </main>
    </div>
  );
}
