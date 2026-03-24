"use client";

import React, { useMemo, useState } from "react";
import type { SpanNode } from "@/lib/api";

interface WaterfallTimelineProps {
    spans: SpanNode[];
    onSpanClick?: (span: SpanNode) => void;
}

const SPAN_COLORS: Record<string, string> = {
    llm_call:          "#a78bfa",   // soft violet
    tool_call:         "#f59e0b",   // amber
    agent_handoff:     "#60a5fa",   // blue
    enforcement_check: "#22c55e",   // green
    guardrail:         "#f59e0b",   // amber
    session:           "#64748b",   // slate
};

const SPAN_TYPE_LABELS: Record<string, string> = {
    llm_call:          "LLM",
    tool_call:         "TOOL",
    agent_handoff:     "HANDOFF",
    enforcement_check: "ENFORCE",
    guardrail:         "GUARD",
    session:           "SESSION",
};

export function WaterfallTimeline({ spans, onSpanClick }: WaterfallTimelineProps) {
    const [hoveredSpan, setHoveredSpan] = useState<number | null>(null);

    const { minTime, maxTime, flatList } = useMemo(() => {
        const validSpans = spans
            .filter((s) => s.start_time)
            .map((s) => {
                const st = new Date(s.start_time!).getTime();
                const et = s.end_time ? new Date(s.end_time).getTime() : st + (s.latency_ms ?? 10);
                return { ...s, st, et };
            })
            .sort((a, b) => a.st - b.st);

        const minT = validSpans.reduce((min, s) => Math.min(min, s.st), Infinity);
        const maxT = validSpans.reduce((max, s) => Math.max(max, s.et), -Infinity);

        const depthMap = new Map<string, number>();
        const findDepth = (id: string, parentId: string | null): number => {
            if (!parentId) return 0;
            if (depthMap.has(id)) return depthMap.get(id)!;
            const parent = validSpans.find(s => s.span_id === parentId);
            if (!parent) return 0;
            const d = 1 + findDepth(parent.span_id, parent.parent_span_id);
            depthMap.set(id, d);
            return d;
        };

        const flat = validSpans.map(s => ({ ...s, depth: findDepth(s.span_id, s.parent_span_id) }));

        return {
            minTime: minT === Infinity ? 0 : minT,
            maxTime: maxT === -Infinity ? 100 : maxT,
            flatList: flat,
        };
    }, [spans]);

    if (flatList.length === 0) {
        return (
            <div style={{ padding: "40px", textAlign: "center", color: "var(--text-dim)", fontSize: 13, fontFamily: "var(--font-mono)" }}>
                No timing data available.
            </div>
        );
    }

    const totalMs = maxTime - minTime || 1;
    const durationStr = (totalMs / 1000).toFixed(2);

    // Legend entries (unique types present)
    const presentTypes = Array.from(new Set(flatList.map(s => s.span_type)));

    return (
        <div style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
        }}>
            {/* Header */}
            <div style={{
                padding: "10px 16px",
                borderBottom: "1px solid var(--border-subtle)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 16,
                flexWrap: "wrap",
            }}>
                <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                    Execution Timeline
                </span>
                <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                    {presentTypes.map(t => (
                        <span key={t} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                            <span style={{ width: 10, height: 10, borderRadius: 2, background: SPAN_COLORS[t] ?? "#64748b", display: "inline-block", flexShrink: 0 }} />
                            {SPAN_TYPE_LABELS[t] ?? t}
                        </span>
                    ))}
                    <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                        total: <strong style={{ color: "var(--text-primary)" }}>{durationStr}s</strong> · {flatList.length} spans
                    </span>
                </div>
            </div>

            <div style={{ padding: "12px 0 16px", overflowX: "auto", minWidth: 0 }}>
                {/* Time axis */}
                <div style={{ display: "flex", margin: "0 16px 10px 180px", position: "relative", height: 18 }}>
                    {[0, 0.25, 0.5, 0.75, 1].map((pct) => (
                        <div key={pct} style={{ position: "absolute", left: `${pct * 100}%`, transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
                            <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                                {((pct * totalMs)).toFixed(0)}ms
                            </span>
                            <div style={{ width: 1, height: 4, background: "var(--border-default)" }} />
                        </div>
                    ))}
                </div>

                {/* Rows */}
                <div style={{ display: "flex", flexDirection: "column", position: "relative" }}>
                    {/* Background grid lines */}
                    <div style={{ position: "absolute", left: 180, right: 16, top: 0, bottom: 0, pointerEvents: "none", zIndex: 0 }}>
                        {[0.25, 0.5, 0.75].map((pct) => (
                            <div key={pct} style={{ position: "absolute", left: `${pct * 100}%`, top: 0, bottom: 0, borderLeft: "1px dashed rgba(100,116,139,0.18)" }} />
                        ))}
                    </div>

                    {flatList.map((s, idx) => {
                        const isHover = hoveredSpan === s.id;
                        const leftPct = ((s.st - minTime) / totalMs) * 100;
                        const widthPct = Math.max(0.8, ((s.et - s.st) / totalMs) * 100);
                        const color = SPAN_COLORS[s.span_type] ?? "#64748b";
                        const label = SPAN_TYPE_LABELS[s.span_type] ?? s.span_type;

                        return (
                            <div
                                key={s.id}
                                onMouseEnter={() => setHoveredSpan(s.id)}
                                onMouseLeave={() => setHoveredSpan(null)}
                                onClick={() => onSpanClick && onSpanClick(s)}
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    padding: "3px 16px 3px 0",
                                    background: isHover ? "var(--bg-2)" : idx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.012)",
                                    cursor: onSpanClick ? "pointer" : "default",
                                    position: "relative",
                                    zIndex: 1,
                                    transition: "background 0.1s",
                                    minHeight: 28,
                                }}
                            >
                                {/* Label column */}
                                <div style={{
                                    width: 180,
                                    minWidth: 180,
                                    paddingLeft: 16 + s.depth * 10,
                                    paddingRight: 10,
                                    display: "flex",
                                    flexDirection: "column",
                                    justifyContent: "center",
                                }}>
                                    <span style={{
                                        fontSize: 12,
                                        fontFamily: "var(--font-mono)",
                                        color: isHover ? "var(--text-primary)" : "var(--text-secondary)",
                                        whiteSpace: "nowrap",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        fontWeight: isHover ? 600 : 400,
                                        lineHeight: 1.3,
                                    }} title={s.name}>
                                        {s.name}
                                    </span>
                                    <span style={{
                                        fontSize: 10,
                                        fontFamily: "var(--font-mono)",
                                        color: color,
                                        textTransform: "uppercase",
                                        letterSpacing: "0.05em",
                                        opacity: 0.85,
                                    }}>
                                        {label}
                                    </span>
                                </div>

                                {/* Bar track */}
                                <div style={{ flex: 1, position: "relative", height: 20 }}>
                                    {/* Track background */}
                                    <div style={{ position: "absolute", inset: 0, background: "rgba(255,255,255,0.025)", borderRadius: 3 }} />
                                    {/* Span bar */}
                                    <div style={{
                                        position: "absolute",
                                        left: `${leftPct}%`,
                                        width: `${widthPct}%`,
                                        top: 2,
                                        bottom: 2,
                                        background: color,
                                        opacity: isHover ? 1 : 0.65,
                                        borderRadius: 3,
                                        transition: "opacity 0.12s",
                                        boxShadow: isHover ? `0 0 8px ${color}55` : "none",
                                    }} />
                                    {/* Hover label */}
                                    {isHover && (
                                        <div style={{
                                            position: "absolute",
                                            left: `calc(${Math.min(leftPct + widthPct, 85)}% + 6px)`,
                                            top: "50%",
                                            transform: "translateY(-50%)",
                                            fontSize: 11,
                                            fontFamily: "var(--font-mono)",
                                            color: "var(--text-secondary)",
                                            whiteSpace: "nowrap",
                                            background: "var(--bg-3)",
                                            padding: "2px 6px",
                                            borderRadius: "var(--radius-sm)",
                                            border: "1px solid var(--border-subtle)",
                                            zIndex: 10,
                                            pointerEvents: "none",
                                        }}>
                                            {s.latency_ms != null ? `${s.latency_ms}ms` : "—"}
                                            {s.cost_usd ? ` · $${s.cost_usd.toFixed(5)}` : ""}
                                            {s.tokens_in ? ` · ${s.tokens_in}→${s.tokens_out ?? 0}tkn` : ""}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
