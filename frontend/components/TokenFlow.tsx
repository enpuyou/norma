"use client";

import { ResponsiveContainer, Sankey, Tooltip } from "recharts";
import type { ContextRoute } from "@/lib/types";

export function TokenFlow({ routes }: { routes: ContextRoute[] }) {
  if (!routes.length) {
    return (
      <div style={{ padding: "12px 14px", border: "1px dashed var(--border-subtle)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
        No token-routing data available.
      </div>
    );
  }

  const nodes = [{ name: "orchestrator" }, ...routes.map((r) => ({ name: r.subagent }))];
  const links = routes.map((r, idx) => ({ source: 0, target: idx + 1, value: Math.max(1, r.tokens_sent) }));

  return (
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "8px 10px" }}>
      <div style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", marginBottom: 6 }}>TOKEN FLOW SANKEY</div>
      <div style={{ height: 230 }}>
        <ResponsiveContainer width="100%" height="100%">
          <Sankey
            data={{ nodes, links }}
            nodePadding={28}
            margin={{ left: 10, right: 10, top: 10, bottom: 10 }}
            link={{ stroke: "#60a5fa" }}
          >
            <Tooltip contentStyle={{ background: "#111827", border: "1px solid #334155", borderRadius: 6, color: "#e2e8f0" }} />
          </Sankey>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
