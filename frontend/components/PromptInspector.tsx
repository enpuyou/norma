"use client";

import React, { useState } from "react";
import type { PromptSnapshot } from "@/lib/api";

interface PromptInspectorProps {
    prompts: PromptSnapshot[];
}

export function PromptInspector({ prompts }: PromptInspectorProps) {
    const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set());

    if (prompts.length === 0) {
        return (
            <div style={{ padding: "40px", textAlign: "center", color: "var(--text-dim)", fontSize: 13, fontFamily: "var(--font-mono)" }}>
                No prompt snapshots captured for this run.
            </div>
        );
    }

    const toggleExpand = (index: number) => {
        setExpandedIndices(prev => {
            const next = new Set(prev);
            if (next.has(index)) next.delete(index);
            else next.add(index);
            return next;
        });
    };

    return (
        <div style={{
            background: "var(--bg-1)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
        }}>
            <div style={{
                padding: "12px 16px",
                borderBottom: "1px solid var(--border-subtle)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
            }}>
                <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Prompt Inspector
                </span>
                <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-dim)", letterSpacing: "0.02em" }}>
                    {prompts.length} snapshot{prompts.length !== 1 ? "s" : ""}
                </span>
            </div>

            <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: 16 }}>
                {prompts.map((p, idx) => {
                    const isSystem = p.role === "system";
                    const isUser = p.role === "user";
                    const isAssistant = p.role === "assistant";
                    const isTool = p.role === "tool";
                    const isExpanded = expandedIndices.has(idx);

                    let bgColor = "var(--bg-3)";
                    let borderColor = "var(--border-subtle)";
                    let textColor = "var(--text-secondary)";
                    let labelColor = "var(--text-dim)";

                    if (isSystem) {
                        bgColor = "var(--bg-2)";
                        textColor = "var(--amber)";
                    } else if (isUser) {
                        bgColor = "rgba(168,85,247,0.05)";
                        borderColor = "rgba(168,85,247,0.2)";
                        labelColor = "var(--purple)";
                        textColor = "var(--text-primary)";
                    } else if (isAssistant) {
                        bgColor = "rgba(59,130,246,0.05)";
                        borderColor = "rgba(59,130,246,0.2)";
                        labelColor = "var(--blue)";
                        textColor = "var(--text-primary)";
                    } else if (isTool) {
                        bgColor = "var(--bg-2)";
                        labelColor = "var(--cyan)";
                    }

                    let content = p.content || "";
                    const isLong = content.length > 500;
                    if (!isExpanded && isLong) {
                        content = content.slice(0, 500) + "...";
                    }

                    return (
                        <div
                            key={p.id}
                            style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 6,
                                padding: "12px 14px",
                                background: bgColor,
                                border: `1px solid ${borderColor}`,
                                borderRadius: "var(--radius-sm)",
                                alignSelf: isUser ? "flex-end" : "flex-start",
                                maxWidth: isSystem ? "100%" : "85%",
                                width: isSystem ? "100%" : "auto",
                            }}
                        >
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
                                <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.05em", color: labelColor, fontWeight: 600 }}>
                                    {p.role}
                                </span>
                                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                                    {p.token_count !== null && (
                                        <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                                            {p.token_count} tkn
                                        </span>
                                    )}
                                    <span style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                                        {p.span_id}
                                    </span>
                                </div>
                            </div>

                            <pre style={{
                                margin: 0,
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                                fontFamily: "var(--font-mono)",
                                fontSize: 12,
                                color: textColor,
                                lineHeight: 1.5,
                            }}>
                                {content}
                            </pre>

                            {isLong && (
                                <button
                                    onClick={() => toggleExpand(idx)}
                                    style={{
                                        all: "unset",
                                        cursor: "pointer",
                                        alignSelf: "flex-start",
                                        fontSize: 12,
                                        fontFamily: "var(--font-mono)",
                                        color: "var(--amber)",
                                        marginTop: 4,
                                    }}
                                >
                                    {isExpanded ? "Show less" : "Show more"}
                                </button>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
