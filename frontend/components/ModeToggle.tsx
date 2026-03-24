"use client";

import { useMode } from "@/hooks/useMode";

export function ModeToggle() {
  const { mode, setMode } = useMode();

  return (
    <div
      style={{
        display: "inline-flex",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-sm)",
        overflow: "hidden",
        fontSize: "11px",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontFamily: "var(--font-mono)",
      }}
    >
      <button
        onClick={() => setMode("vp")}
        style={{
          padding: "5px 14px",
          background: mode === "vp" ? "var(--amber)" : "transparent",
          color: mode === "vp" ? "var(--text-inverse)" : "var(--text-secondary)",
          border: "none",
          cursor: "pointer",
          fontFamily: "inherit",
          fontSize: "inherit",
          letterSpacing: "inherit",
          textTransform: "inherit",
          fontWeight: mode === "vp" ? 600 : 400,
          transition: "all 0.15s ease",
        }}
      >
        MANAGE
      </button>
      <div
        style={{
          width: "1px",
          background: "var(--border-default)",
        }}
      />
      <button
        onClick={() => setMode("engineer")}
        style={{
          padding: "5px 14px",
          background: mode === "engineer" ? "var(--amber)" : "transparent",
          color: mode === "engineer" ? "var(--text-inverse)" : "var(--text-secondary)",
          border: "none",
          cursor: "pointer",
          fontFamily: "inherit",
          fontSize: "inherit",
          letterSpacing: "inherit",
          textTransform: "inherit",
          fontWeight: mode === "engineer" ? 600 : 400,
          transition: "all 0.15s ease",
        }}
      >
        DEV
      </button>
    </div>
  );
}
