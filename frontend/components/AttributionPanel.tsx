"use client";

import type { Attribution } from "@/lib/types";

export function AttributionPanel({ items }: { items: Attribution[] }) {
  if (!items.length) {
    return (
      <div style={{ padding: "12px 14px", border: "1px dashed var(--border-subtle)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
        No attribution evidence yet.
      </div>
    );
  }

  return (
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
      <div style={{ padding: "9px 12px", borderBottom: "1px solid var(--border-subtle)", fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
        FAILURE ATTRIBUTION
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {items.map((item) => {
          const conf = item.confidence;
          const confColor = conf >= 0.75 ? "var(--green)" : conf >= 0.6 ? "var(--amber)" : "var(--red)";
          const occurrenceCount = item.occurrence_count ?? 1;
          const latestTicket = item.latest_ticket_id ?? item.ticket_id;
          return (
            <div key={`${item.ticket_id}-${item.most_likely_node}`} style={{ padding: "10px 12px", borderTop: "1px solid var(--border-subtle)", display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>latest ticket #{latestTicket}</span>
                <span style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>{item.most_likely_node}</span>
                {occurrenceCount > 1 ? (
                  <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "1px 6px" }}>
                    {occurrenceCount}x
                  </span>
                ) : null}
                <span style={{ marginLeft: "auto", fontSize: 10, color: confColor, fontFamily: "var(--font-mono)" }}>{(item.confidence * 100).toFixed(0)}%</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-primary)", lineHeight: 1.45 }}>{item.evidence}</div>
              {item.ticket_ids && item.ticket_ids.length > 1 ? (
                <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                  tickets: {item.ticket_ids.slice(0, 6).join(", ")}{item.ticket_ids.length > 6 ? "…" : ""}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
