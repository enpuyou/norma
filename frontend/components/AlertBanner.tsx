"use client";

import type { Alert } from "@/lib/types";
import { useMode } from "@/hooks/useMode";
import { useState } from "react";

const SEVERITY_STYLES = {
  critical: { border: "rgba(239,68,68,0.4)", bg: "rgba(239,68,68,0.06)", icon: "⊗", iconColor: "#ef4444" },
  warning:  { border: "rgba(234,179,8,0.4)", bg: "rgba(234,179,8,0.06)",  icon: "⚠", iconColor: "#eab308" },
  info:     { border: "rgba(96,165,250,0.4)", bg: "rgba(96,165,250,0.06)", icon: "ℹ", iconColor: "#60a5fa" },
};

export function AlertBanner({ alert, onDismiss, frequency }: { alert: Alert; onDismiss?: () => void; frequency?: number }) {
  const { mode } = useMode();
  // Local fallback if no parent dismiss handler provided
  const [localDismissed, setLocalDismissed] = useState(false);

  if (localDismissed) return null;

  const s = SEVERITY_STYLES[alert.severity];
  const message = mode === "vp" ? alert.vp_message : alert.engineer_message;

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "10px 14px",
        background: s.bg,
        border: `1px solid ${s.border}`,
        borderRadius: "var(--radius-sm)",
        fontFamily: "var(--font-mono)",
        position: "relative",
      }}
    >
      {/* Severity icon */}
      <span style={{ fontSize: 14, color: s.iconColor, flexShrink: 0, lineHeight: 1.5 }}>
        {s.icon}
      </span>
      {frequency && frequency > 1 && (
        <span style={{
          alignSelf: "flex-start",
          marginTop: 2,
          padding: "1px 5px",
          background: "rgba(245,158,11,0.12)",
          border: "1px solid rgba(245,158,11,0.25)",
          borderRadius: "var(--radius-sm)",
          fontSize: "9px",
          fontFamily: "var(--font-mono)",
          color: "var(--amber)",
          letterSpacing: "0.04em",
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}>
          ×{frequency}
        </span>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>
        {mode === "engineer" && (
          <div style={{ display: "flex", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
            <span style={{ fontSize: "10px", color: s.iconColor, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              {alert.severity}
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>·</span>
            <span style={{ fontSize: "10px", color: "var(--text-secondary)" }}>
              {alert.agent_name}
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>·</span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
              {alert.window} · n={alert.sample_n}
            </span>
          </div>
        )}
        <p style={{ fontSize: "12px", color: "var(--text-primary)", lineHeight: 1.6, fontFamily: mode === "vp" ? "var(--font-sans)" : "var(--font-mono)", fontWeight: 300 }}>
          {message}
        </p>
        {mode === "engineer" && (
          <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
            <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
              contract change: {alert.contract_change_in_window ? <span style={{ color: "var(--amber)" }}>YES</span> : "none"}
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
              model change: {alert.model_change_in_window ? <span style={{ color: "var(--amber)" }}>YES</span> : "none"}
            </span>
            <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
              {new Date(alert.timestamp).toLocaleString()}
            </span>
          </div>
        )}
      </div>

      {/* Dismiss */}
      <button
        onClick={(e) => { e.stopPropagation(); if (onDismiss) { onDismiss(); } else { setLocalDismissed(true); } }}
        style={{
          background: "none",
          border: "none",
          color: "var(--text-dim)",
          cursor: "pointer",
          fontSize: 14,
          flexShrink: 0,
          lineHeight: 1,
          padding: "2px 4px",
        }}
        title="Dismiss"
      >
        ×
      </button>
    </div>
  );
}
