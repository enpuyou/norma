"use client";

import { useState, useRef, useEffect } from "react";
import { askQuestion } from "@/lib/api";

interface QAMessage {
  role: "user" | "assistant";
  text: string;
  confidence?: string;
  data_sources?: string[];
  caveats?: string[];
  ts: number;
}

const CONFIDENCE_COLOR: Record<string, string> = {
  high:               "var(--green)",
  medium:             "var(--amber)",
  low:                "#f97316",
  cannot_determine:   "var(--text-dim)",
};

const SUGGESTIONS = [
  "Why did financial-reader-v1 trust score drop?",
  "What violations happened fleet-wide?",
  "Which agent has the best quality score?",
  "What is the average cost per run?",
  "How many runs failed this week?",
];

export function QAPanel({ agentId }: { agentId?: string }) {
  const [messages, setMessages] = useState<QAMessage[]>([]);
  const [input, setInput]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [expanded, setExpanded] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function submit(question: string) {
    if (!question.trim() || loading) return;
    const q = question.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q, ts: Date.now() }]);
    setLoading(true);

    try {
      const res = await askQuestion(q, agentId);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.answer,
          confidence: res.confidence,
          data_sources: res.data_sources,
          caveats: res.caveats,
          ts: Date.now(),
        },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: "Could not reach the backend. Is the server running on port 8080?",
          confidence: "cannot_determine",
          data_sources: [],
          caveats: [],
          ts: Date.now(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-md)",
        fontFamily: "var(--font-mono)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* ── Header ─────────────────────────────────────────────── */}
      <button
        onClick={() => setExpanded((e) => !e)}
        style={{
          all: "unset",
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "10px 14px",
          borderBottom: expanded ? "1px solid var(--border-subtle)" : "none",
        }}
      >
        <span style={{ fontSize: "11px", color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Conversational Q&A
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: "9px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
            {messages.length > 0 ? `${Math.floor(messages.length / 2)} question${Math.floor(messages.length / 2) !== 1 ? "s" : ""}` : "grounded in run data"}
          </span>
          <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            {expanded ? "▾" : "▸"}
          </span>
        </div>
      </button>

      {expanded && (
        <>
          {/* ── Message thread ──────────────────────────────────── */}
          <div
            style={{
              maxHeight: 340,
              overflowY: "auto",
              padding: "12px 14px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            {messages.length === 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Suggested questions
                </span>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => submit(s)}
                    style={{
                      all: "unset",
                      cursor: "pointer",
                      fontSize: "11px",
                      color: "var(--text-secondary)",
                      padding: "5px 9px",
                      background: "var(--bg-1)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      letterSpacing: "0.02em",
                      transition: "color 0.15s, border-color 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = "var(--amber)";
                      (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(245,158,11,0.3)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.color = "var(--text-secondary)";
                      (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border-subtle)";
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: msg.role === "user" ? "flex-end" : "flex-start" }}>
                {/* bubble */}
                <div
                  style={{
                    maxWidth: "88%",
                    padding: "8px 12px",
                    borderRadius: "var(--radius-sm)",
                    fontSize: "12px",
                    lineHeight: 1.6,
                    whiteSpace: "pre-wrap",
                    ...(msg.role === "user"
                      ? {
                          background: "rgba(245,158,11,0.08)",
                          border: "1px solid rgba(245,158,11,0.15)",
                          color: "var(--amber)",
                          alignSelf: "flex-end",
                        }
                      : {
                          background: "var(--bg-1)",
                          border: "1px solid var(--border-subtle)",
                          color: "var(--text-primary)",
                        }),
                  }}
                >
                  {msg.text}
                </div>

                {/* metadata strip (assistant only) */}
                {msg.role === "assistant" && msg.confidence && (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", paddingLeft: 2 }}>
                    <span style={{
                      fontSize: "9px",
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      color: CONFIDENCE_COLOR[msg.confidence] ?? "var(--text-dim)",
                    }}>
                      confidence: {msg.confidence.replace("_", " ")}
                    </span>
                    {msg.data_sources && msg.data_sources.length > 0 && (
                      <span style={{ fontSize: "9px", color: "var(--text-dim)", letterSpacing: "0.04em" }}>
                        · {msg.data_sources.slice(0, 3).join(", ")}
                      </span>
                    )}
                  </div>
                )}

                {/* caveats */}
                {msg.role === "assistant" && msg.caveats && msg.caveats.length > 0 && (
                  <div style={{ paddingLeft: 2, paddingTop: 2 }}>
                    {msg.caveats.map((c, ci) => (
                      <div key={ci} style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.02em" }}>
                        ⚠ {c}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, paddingLeft: 2 }}>
                <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
                  querying database
                </span>
                <span style={{ fontSize: "14px", color: "var(--amber)", animation: "pulse 1.2s ease-in-out infinite" }}>
                  ···
                </span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* ── Input ───────────────────────────────────────────── */}
          <div
            style={{
              borderTop: "1px solid var(--border-subtle)",
              padding: "10px 14px",
              display: "flex",
              gap: 8,
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(input); } }}
              placeholder="Ask about trust scores, violations, cost, quality…"
              disabled={loading}
              style={{
                flex: 1,
                background: "var(--bg-1)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-sm)",
                padding: "7px 10px",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                color: "var(--text-primary)",
                outline: "none",
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = "rgba(245,158,11,0.35)"; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = "var(--border-default)"; }}
            />
            <button
              onClick={() => submit(input)}
              disabled={loading || !input.trim()}
              style={{
                all: "unset",
                cursor: loading || !input.trim() ? "default" : "pointer",
                padding: "7px 14px",
                background: loading || !input.trim() ? "var(--bg-4)" : "rgba(245,158,11,0.12)",
                color: loading || !input.trim() ? "var(--text-dim)" : "var(--amber)",
                border: `1px solid ${loading || !input.trim() ? "var(--border-subtle)" : "rgba(245,158,11,0.25)"}`,
                borderRadius: "var(--radius-sm)",
                fontSize: "11px",
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                transition: "all 0.15s",
              }}
            >
              Ask
            </button>
          </div>
        </>
      )}
    </div>
  );
}
