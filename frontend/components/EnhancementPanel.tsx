"use client";

import { useEffect, useState } from "react";
import { applyEnhancement, getEnhancements, type Enhancement } from "@/lib/api";

const PRIORITY_COLORS: Record<string, string> = {
  high: "var(--red)",
  medium: "var(--amber)",
  low: "var(--blue)",
};

export function EnhancementPanel({ agentId }: { agentId: string }) {
  const [items, setItems] = useState<Enhancement[]>([]);
  const [loading, setLoading] = useState(true);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [dismissedIds, setDismissedIds] = useState<string[]>([]);

  const storageKey = `norma:enhancements:dismissed:${agentId}`;

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      const parsed = raw ? (JSON.parse(raw) as string[]) : [];
      setDismissedIds(Array.isArray(parsed) ? parsed : []);
    } catch {
      setDismissedIds([]);
    }
  }, [storageKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getEnhancements(agentId)
      .then((res) => {
        if (!cancelled) setItems(res);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  async function onApply(item: Enhancement) {
    const approver = window.prompt("Apply as user", "admin") ?? "";
    if (!approver.trim()) return;
    setApplyingId(item.id);
    setStatus("");
    try {
      const res = await applyEnhancement(agentId, item.yaml_snippet, item.type, approver.trim());
      setStatus(`Applied ${item.type} to contract v${res.contract_version}.`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Failed to apply enhancement.");
    } finally {
      setApplyingId(null);
    }
  }

  function onDismiss(item: Enhancement) {
    const next = dismissedIds.includes(item.id) ? dismissedIds : [...dismissedIds, item.id];
    setDismissedIds(next);
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // no-op when storage unavailable
    }
  }

  const visibleItems = items.filter((item) => !dismissedIds.includes(item.id));

  if (loading) {
    return null;
  }

  if (!visibleItems.length) {
    return null;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
      <div style={{ fontSize: "11px", color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
        Enhancement Engine
      </div>
      {status && (
        <div style={{ fontSize: "11px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "8px 10px", background: "var(--bg-1)" }}>
          {status}
        </div>
      )}
      {visibleItems.map((item) => {
        const color = PRIORITY_COLORS[item.priority] ?? "var(--blue)";
        return (
          <div
            key={item.id}
            style={{
              border: `1px solid ${color}33`,
              background: `${color}11`,
              borderRadius: "var(--radius-sm)",
              padding: "10px 12px",
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
              <div style={{ fontSize: "12px", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                {item.title}
              </div>
              <span style={{ fontSize: "9px", color, fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {item.priority}
              </span>
            </div>
            <div style={{ fontSize: "11px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
              {item.evidence}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                confidence: {item.confidence}
                {item.span_ids.length ? ` · spans: ${item.span_ids.join(", ")}` : ""}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <button
                  onClick={() => onDismiss(item)}
                  disabled={applyingId !== null}
                  style={{
                    border: "1px solid var(--border-default)",
                    background: "transparent",
                    color: "var(--text-dim)",
                    borderRadius: "var(--radius-sm)",
                    padding: "3px 10px",
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.04em",
                    cursor: applyingId !== null ? "wait" : "pointer",
                    opacity: applyingId !== null ? 0.6 : 1,
                  }}
                >
                  Dismiss
                </button>
                <button
                  onClick={() => onApply(item)}
                  disabled={applyingId !== null}
                  style={{
                    border: `1px solid ${color}55`,
                    background: `${color}22`,
                    color,
                    borderRadius: "var(--radius-sm)",
                    padding: "3px 10px",
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.04em",
                    cursor: applyingId !== null ? "wait" : "pointer",
                    opacity: applyingId !== null ? 0.6 : 1,
                  }}
                >
                  {applyingId === item.id ? "Applying…" : "Apply to Contract"}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
