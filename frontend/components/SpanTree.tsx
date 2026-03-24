"use client";

import { useState } from "react";
import type { SpanNode } from "@/lib/api";

function SpanNodeView({ node, depth = 0 }: { node: SpanNode; depth?: number }) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  const statusColor =
    node.status === "ok" ? "var(--green)" : node.status === "blocked" ? "var(--red)" : "var(--amber)";

  return (
    <div style={{ marginLeft: depth * 14, marginBottom: 6 }}>
      <div
        style={{
          border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-sm)",
          background: "var(--bg-2)",
          overflow: "hidden",
        }}
      >
        <div
          onClick={() => hasChildren && setOpen((x) => !x)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "7px 10px",
            cursor: hasChildren ? "pointer" : "default",
            borderBottom: open && hasChildren ? "1px solid var(--border-subtle)" : "none",
          }}
        >
          <span style={{ width: 12, color: "var(--text-dim)", fontSize: 10 }}>{hasChildren ? (open ? "▾" : "▸") : ""}</span>
          <span style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{node.span_type}</span>
          <span style={{ fontSize: 11, color: "var(--text-primary)", fontFamily: "var(--font-mono)", flex: 1 }}>{node.name}</span>
          <span style={{ fontSize: 12, color: statusColor, fontFamily: "var(--font-mono)" }}>{node.status}</span>
          {node.tokens_in !== null && <span style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>in:{node.tokens_in}</span>}
          {node.tokens_out !== null && <span style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>out:{node.tokens_out}</span>}
          {node.cost_usd !== null && <span style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>${node.cost_usd.toFixed(5)}</span>}
          {node.latency_ms !== null && <span style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{node.latency_ms}ms</span>}
        </div>

        {open && (
          <div style={{ padding: "6px 10px", display: "flex", flexDirection: "column", gap: 4 }}>
            {node.attributes && (
              <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)", overflowX: "auto" }}>
                attrs: {JSON.stringify(node.attributes)}
              </div>
            )}
            {node.input_data && (
              <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)", overflowX: "auto" }}>
                in: {JSON.stringify(node.input_data)}
              </div>
            )}
            {node.output_data && (
              <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)", overflowX: "auto" }}>
                out: {JSON.stringify(node.output_data)}
              </div>
            )}
          </div>
        )}
      </div>

      {open && hasChildren && (
        <div style={{ marginTop: 6 }}>
          {node.children.map((child) => (
            <SpanNodeView key={child.span_id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SpanTree({ roots }: { roots: SpanNode[] }) {
  if (!roots.length) {
    return (
      <div style={{ padding: 12, border: "1px dashed var(--border-subtle)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: 11 }}>
        No spans captured for this run.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {roots.map((n) => (
        <SpanNodeView key={n.span_id} node={n} />
      ))}
    </div>
  );
}
