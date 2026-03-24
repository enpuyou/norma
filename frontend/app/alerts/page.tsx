"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getAlerts } from "@/lib/api";
import type { Alert } from "@/lib/types";
import { useMode } from "@/hooks/useMode";
import { ModeToggle } from "@/components/ModeToggle";

const SEVERITY_STYLES = {
  critical: { border: "rgba(239,68,68,0.4)", bg: "rgba(239,68,68,0.06)", icon: "⊗", iconColor: "#ef4444", labelColor: "var(--red)" },
  warning:  { border: "rgba(234,179,8,0.4)",  bg: "rgba(234,179,8,0.06)",  icon: "⚠", iconColor: "#eab308", labelColor: "var(--amber)" },
  info:     { border: "rgba(96,165,250,0.4)", bg: "rgba(96,165,250,0.06)", icon: "ℹ", iconColor: "#60a5fa", labelColor: "var(--blue)" },
};

const STORAGE_KEY = "norma_dismissed_alerts";

function loadDismissed(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return new Set(JSON.parse(stored) as string[]);
  } catch { /* ignore */ }
  return new Set();
}

function saveDismissed(ids: Set<string>) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids])); } catch { /* ignore */ }
}

export default function AlertsPage() {
  const { mode } = useMode();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => loadDismissed());
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [showDismissed, setShowDismissed] = useState(false);

  useEffect(() => {
    getAlerts().then(setAlerts).catch(() => {});
  }, []);

  const handleDismiss = (id: string) => {
    setDismissedIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      saveDismissed(next);
      return next;
    });
  };

  const handleRestore = (id: string) => {
    setDismissedIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      saveDismissed(next);
      return next;
    });
  };

  const handleDismissAll = () => {
    const next = new Set(alerts.map((a) => String(a.id)));
    saveDismissed(next);
    setDismissedIds(next);
  };

  const agentIds = [...new Set(alerts.map((a) => a.agent_id))].sort();

  const filtered = alerts.filter((a) => {
    const isDismissed = dismissedIds.has(String(a.id));
    if (!showDismissed && isDismissed) return false;
    if (severityFilter && a.severity !== severityFilter) return false;
    if (agentFilter && a.agent_id !== agentFilter) return false;
    return true;
  });

  // Deduplicate by (agent_id + metric) — keep the most recent, show frequency badge
  const dedupedMap = filtered.reduce((acc, alert) => {
    const key = `${alert.agent_id}::${alert.metric}`;
    const existing = acc.get(key);
    if (!existing) {
      acc.set(key, { alert, count: 1 });
    } else {
      // Prefer the most recent timestamp
      const existingTs = new Date(existing.alert.timestamp).getTime();
      const thisTs = new Date(alert.timestamp).getTime();
      acc.set(key, {
        alert: thisTs > existingTs ? alert : existing.alert,
        count: existing.count + 1,
      });
    }
    return acc;
  }, new Map<string, { alert: Alert; count: number }>());

  const deduped = [...dedupedMap.values()];

  const activeCount = alerts.filter((a) => !dismissedIds.has(String(a.id))).length;
  const dismissedCount = alerts.filter((a) => dismissedIds.has(String(a.id))).length;

  const inputStyle: React.CSSProperties = {
    padding: "4px 8px",
    background: "var(--bg-2)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--radius-sm)",
    color: "var(--text-secondary)",
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    cursor: "pointer",
  };

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-0)", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
      {/* Header */}
      <header style={{
        borderBottom: "1px solid var(--border-default)",
        padding: "0 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        height: 52,
        position: "sticky",
        top: 0,
        background: "var(--bg-0)",
        zIndex: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/" style={{ textDecoration: "none" }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color: "var(--text-default)", letterSpacing: "0.04em" }}>
              norma.ai
            </span>
          </Link>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {[
              { label: "DASHBOARD", href: "/", active: false },
              { label: "REGISTRY", href: "/agents", active: false },
              { label: "LOG", href: "/runs", active: false },
              { label: "ALERTS", href: "/alerts", active: true },
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
          {activeCount > 0 && (
            <span style={{
              padding: "1px 7px",
              background: "rgba(239,68,68,0.1)",
              border: "1px solid rgba(239,68,68,0.2)",
              borderRadius: "var(--radius-sm)",
              color: "var(--red)",
              fontSize: 9,
            }}>
              {activeCount} active
            </span>
          )}
          {dismissedCount > 0 && (
            <span style={{
              padding: "1px 7px",
              background: "var(--bg-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-dim)",
              fontSize: 9,
            }}>
              {dismissedCount} dismissed
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ModeToggle />
        </div>
      </header>

      <main style={{ maxWidth: 900, margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Filter bar */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.07em", textTransform: "uppercase", marginRight: 4 }}>Filter</span>
          <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} style={inputStyle}>
            <option value="">ALL SEVERITIES</option>
            <option value="critical">CRITICAL</option>
            <option value="warning">WARNING</option>
            <option value="info">INFO</option>
          </select>
          <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} style={inputStyle}>
            <option value="">ALL AGENTS</option>
            {agentIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-dim)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={showDismissed}
              onChange={(e) => setShowDismissed(e.target.checked)}
              style={{ cursor: "pointer" }}
            />
            show dismissed
          </label>
          {activeCount > 0 && (
            <button
              onClick={handleDismissAll}
              style={{
                marginLeft: "auto",
                padding: "3px 10px",
                background: "transparent",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-dim)",
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                cursor: "pointer",
                letterSpacing: "0.04em",
              }}
            >
              Dismiss all
            </button>
          )}
        </div>

        {/* Alert list */}
        {deduped.length === 0 ? (
          <div style={{
            padding: "40px 20px",
            textAlign: "center",
            border: "1px dashed var(--border-subtle)",
            borderRadius: "var(--radius-md)",
          }}>
            <p style={{ fontSize: 12, color: "var(--text-dim)", margin: 0 }}>
              {showDismissed ? "No alerts match the current filters." : "No active alerts. All clear."}
            </p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {deduped.map(({ alert: a, count: freq }) => {
              const s = SEVERITY_STYLES[a.severity];
              const isDismissed = dismissedIds.has(String(a.id));
              const message = mode === "vp" ? a.vp_message : a.engineer_message;
              return (
                <div
                  key={a.id}
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "12px 14px",
                    background: isDismissed ? "var(--bg-1)" : s.bg,
                    border: `1px solid ${isDismissed ? "var(--border-subtle)" : s.border}`,
                    borderRadius: "var(--radius-sm)",
                    opacity: isDismissed ? 0.5 : 1,
                    transition: "opacity 0.15s",
                  }}
                >
                  <span style={{ fontSize: 14, color: isDismissed ? "var(--text-dim)" : s.iconColor, flexShrink: 0, lineHeight: 1.5 }}>
                    {s.icon}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 8, marginBottom: 4, flexWrap: "wrap", alignItems: "center" }}>
                      <span style={{ fontSize: 12, color: isDismissed ? "var(--text-dim)" : s.labelColor, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                        {a.severity}
                      </span>
                      {freq > 1 && (
                        <span style={{
                          padding: "1px 5px",
                          background: "rgba(245,158,11,0.12)",
                          border: "1px solid rgba(245,158,11,0.25)",
                          borderRadius: "var(--radius-sm)",
                          fontSize: "11px",
                          fontFamily: "var(--font-mono)",
                          color: "var(--amber)",
                          letterSpacing: "0.04em",
                        }}>
                          ×{freq}
                        </span>
                      )}
                      <span style={{ fontSize: 12, color: "var(--text-dim)" }}>·</span>
                      <Link
                        href={`/agents/${a.agent_id}`}
                        style={{ fontSize: 12, color: "var(--text-secondary)", textDecoration: "none" }}
                      >
                        {a.agent_name}
                      </Link>
                      <span style={{ fontSize: 12, color: "var(--text-dim)" }}>·</span>
                      <span style={{ fontSize: 12, color: "var(--text-dim)" }}>{a.metric}</span>
                      {isDismissed && (
                        <span style={{ fontSize: 9, color: "var(--text-dim)", background: "var(--bg-3)", padding: "1px 5px", borderRadius: 3 }}>
                          dismissed
                        </span>
                      )}
                    </div>
                    <p style={{
                      fontSize: 12,
                      color: isDismissed ? "var(--text-dim)" : "var(--text-primary)",
                      lineHeight: 1.6,
                      fontFamily: mode === "vp" ? "var(--font-sans)" : "var(--font-mono)",
                      fontWeight: 300,
                      margin: 0,
                    }}>
                      {message}
                    </p>
                    {mode === "engineer" && (
                      <div style={{ display: "flex", gap: 12, marginTop: 4, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                          {a.window} · n={a.sample_n}
                        </span>
                        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                          contract change: {a.contract_change_in_window ? <span style={{ color: "var(--amber)" }}>YES</span> : "none"}
                        </span>
                        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                          model change: {a.model_change_in_window ? <span style={{ color: "var(--amber)" }}>YES</span> : "none"}
                        </span>
                        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
                          {new Date(a.timestamp).toLocaleString()}
                        </span>
                      </div>
                    )}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, flexShrink: 0 }}>
                    {isDismissed ? (
                      <button
                        onClick={() => handleRestore(String(a.id))}
                        style={{
                          background: "none",
                          border: "1px solid var(--border-subtle)",
                          borderRadius: "var(--radius-sm)",
                          color: "var(--text-dim)",
                          cursor: "pointer",
                          fontSize: 9,
                          fontFamily: "var(--font-mono)",
                          padding: "2px 6px",
                          letterSpacing: "0.04em",
                        }}
                        title="Restore alert"
                      >
                        RESTORE
                      </button>
                    ) : (
                      <button
                        onClick={() => handleDismiss(String(a.id))}
                        style={{
                          background: "none",
                          border: "none",
                          color: "var(--text-dim)",
                          cursor: "pointer",
                          fontSize: 14,
                          lineHeight: 1,
                          padding: "2px 4px",
                        }}
                        title="Dismiss"
                      >
                        ×
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
