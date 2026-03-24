"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useMode } from "@/hooks/useMode";
import { useEventStream } from "@/hooks/useEventStream";
import { ModeToggle } from "@/components/ModeToggle";
import { TrustSparkline } from "@/components/TrustSparkline";
import { AgentGraph } from "@/components/AgentGraph";
import { RecommendationBanner } from "@/components/RecommendationBanner";
import { EnhancementPanel } from "@/components/EnhancementPanel";
import { AttributionPanel } from "@/components/AttributionPanel";
import { MetricsTrendCharts } from "@/components/MetricsTrendCharts";
import { TokenFlow } from "@/components/TokenFlow";
import {
  getAgent,
  getMetrics,
  getAgentMetricTrends,
  getContracts,
  generateContract,
  approveContract,
  disapproveContract,
  updateContract,
  suggestRule,
  type SuggestRuleResult,
  checkAgentChanges,
  type CheckChangesResult,
  getRunSteps,
  type RunStep,
  getRunTree,
  getViolations,
  getAuditLog,
  reviewViolation,
  getContextRoutes,
  getAttributions,
  getRuns,
  exportCompliance,
  compareVersions,
  diffContracts,
  executeAgent,
  deleteAgent,
  getRun,
  getRunSpans,
  getRunMetrics,
  getQualityRubric,
  updateQualityRubric,
  type ExecuteResult,
  type ExecuteStepResult,
  type ExecuteFullResult,
  type ExecuteLLMResult,
  type RunRecord,
  type AgentMetricTrends,
  type RunSpansResponse,
  type RunMetrics,
} from "@/lib/api";
import { SpanTree } from "@/components/SpanTree";
import { WaterfallTimeline } from "@/components/WaterfallTimeline";
import type {
  Agent,
  AgentMetrics,
  Attribution,
  Contract,
  ContractDiff,
  Violation,
  AuditLog,
  ContextRoute,
  Tier,
  VersionComparison,
  RunTreeNode,
} from "@/lib/types";

// ─── YAML diff helper ────────────────────────────────────────────────────────
type DiffLine = { op: "eq" | "ins" | "del"; text: string };

function formatLocalTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function computeYamlDiff(a: string, b: string): DiffLine[] {
  const linesA = a.split("\n");
  const linesB = b.split("\n");
  const m = linesA.length, n = linesB.length;
  // LCS DP table
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = linesA[i - 1] === linesB[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
  // Backtrack
  const result: DiffLine[] = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && linesA[i - 1] === linesB[j - 1]) {
      result.unshift({ op: "eq", text: linesA[i - 1] }); i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({ op: "ins", text: linesB[j - 1] }); j--;
    } else {
      result.unshift({ op: "del", text: linesA[i - 1] }); i--;
    }
  }
  return result;
}

// ─── Tier styling ──────────────────────────────────────────────────────────────
const TIER: Record<Tier, { text: string; bg: string; dot: string }> = {
  restricted: { text: "#ef4444", bg: "rgba(239,68,68,0.10)", dot: "#ef4444" },
  standard: { text: "#60a5fa", bg: "rgba(96,165,250,0.10)", dot: "#60a5fa" },
  trusted: { text: "#22c55e", bg: "rgba(34,197,94,0.10)", dot: "#22c55e" },
};

// ─── Reusable components ───────────────────────────────────────────────────────

function SectionHeader({ title, badge }: { title: string; badge?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
      <span style={{ fontSize: "11px", color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
        {title}
      </span>
      {badge && (
        <span style={{
          fontSize: "11px",
          padding: "1px 6px",
          background: "var(--amber-glow)",
          border: "1px solid rgba(245,158,11,0.2)",
          borderRadius: "var(--radius-sm)",
          color: "var(--amber)",
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.06em",
        }}>
          {badge}
        </span>
      )}
    </div>
  );
}

function MetricCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{
      background: "var(--bg-2)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      padding: "14px 16px",
      display: "flex",
      flexDirection: "column",
      gap: 4,
    }}>
      <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>
        {label}
      </span>
      <span style={{ fontSize: "22px", fontWeight: 600, color: color ?? "var(--text-primary)", fontFamily: "var(--font-mono)", lineHeight: 1 }}>
        {value}
      </span>
      {sub && (
        <span style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}

function Panel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: "var(--bg-2)",
      border: "1px solid var(--border-default)",
      borderRadius: "var(--radius-md)",
      overflow: "hidden",
      ...style,
    }}>
      {children}
    </div>
  );
}

function PanelHeader({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div style={{
      padding: "10px 14px",
      borderBottom: "1px solid var(--border-subtle)",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
    }}>
      <span style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {title}
      </span>
      {right}
    </div>
  );
}

// ─── Metrics Overview Panel ────────────────────────────────────────────────────

function MetricsPanel({ metrics }: { metrics: AgentMetrics | null }) {
  if (!metrics) return null;

  const trustColor = metrics.trust_delta > 0 ? "var(--green)" : metrics.trust_delta < 0 ? "var(--red)" : "var(--text-secondary)";
  const trustArrow = metrics.trust_delta > 0 ? "↑" : metrics.trust_delta < 0 ? "↓" : "→";

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
        <MetricCard
          label="Trust Score"
          value={metrics.trust_end.toFixed(3)}
          sub={`${trustArrow} ${(metrics.trust_delta * 100).toFixed(1)}pp`}
          color={trustColor}
        />
        <MetricCard
          label="Quality"
          value={`${(metrics.avg_quality_score * 100).toFixed(0)}%`}
          sub={`${metrics.n_successful} of ${metrics.n_runs} runs`}
          color={metrics.avg_quality_score >= 0.85 ? "var(--green)" : metrics.avg_quality_score >= 0.75 ? "var(--amber)" : "var(--red)"}
        />
        <MetricCard
          label="Avg Cost"
          value={`$${metrics.avg_cost_usd.toFixed(4)}`}
          sub={metrics.cost_change_wow !== null ? `${metrics.cost_change_wow > 0 ? "+" : ""}${(metrics.cost_change_wow * 100).toFixed(1)}% WoW` : "—"}
        />
        <MetricCard
          label="Completion"
          value={`${(metrics.completion_rate * 100).toFixed(0)}%`}
          sub={`${metrics.n_failed} failed`}
          color={metrics.completion_rate >= 0.95 ? "var(--green)" : "var(--amber)"}
        />
        <MetricCard label="Latency P50" value={`${metrics.latency_p50_ms}ms`} />
        <MetricCard label="Latency P95" value={`${metrics.latency_p95_ms}ms`} />
        <MetricCard
          label="Total Violations"
          value={metrics.total_violations.toString()}
          color={metrics.total_violations === 0 ? "var(--green)" : "var(--red)"}
        />
        <MetricCard
          label="Quality-Adj Cost"
          value={`$${metrics.quality_adj_cost.toFixed(4)}`}
          sub="cost / quality"
        />
      </div>
    </>
  );
}

// ─── Contract Panel ────────────────────────────────────────────────────────────

function ContractPanel({
  contracts,
  agentId,
  onRefresh,
  mode,
}: {
  contracts: Contract[];
  agentId: string;
  onRefresh: () => void;
  mode: "vp" | "engineer";
}) {
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);
  const [disapproving, setDisapproving] = useState<string | null>(null);
  const [expandedYaml, setExpandedYaml] = useState<number | null>(null);
  const [lastMeta, setLastMeta] = useState<{ inferred: string[]; assumed: string[]; requires_input: string[] } | null>(null);
  const [yamlDiff, setYamlDiff] = useState<ContractDiff | null>(null);
  const [metricsCompare, setMetricsCompare] = useState<VersionComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const allVersions = contracts.map((c) => c.version);
  const [diffV1, setDiffV1] = useState<string>("");
  const [diffV2, setDiffV2] = useState<string>("");
  // inline editor state
  const [editYaml, setEditYaml] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // NL rule suggester
  const [nlRuleText, setNlRuleText] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestResult, setSuggestResult] = useState<SuggestRuleResult | null>(null);
  const [nlError, setNlError] = useState<string | null>(null);
  const [nlTargetVersion, setNlTargetVersion] = useState<string | null>(null);

  const active = contracts.find((c) => c.is_active);
  const pending = contracts
    .filter((c) => !c.is_active)
    .sort((a, b) => b.id - a.id);
  const latestPending = pending[0] ?? null;

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const result = await generateContract(agentId);
      if (result.meta) setLastMeta(result.meta as typeof lastMeta);
      onRefresh();
    } catch (err) {
      console.error("Failed to generate contract:", err);
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async (version: string) => {
    setApproving(version);
    try {
      await approveContract(agentId, version, "dashboard-user");
      onRefresh();
    } catch (err) {
      console.error("Failed to approve contract:", err);
    } finally {
      setApproving(null);
    }
  };

  const handleDisapprove = async (version: string) => {
    setDisapproving(version);
    try {
      await disapproveContract(agentId, version, "dashboard-user", "Rejected by reviewer");
      onRefresh();
    } catch (err) {
      console.error("Failed to disapprove contract:", err);
    } finally {
      setDisapproving(null);
    }
  };

  const handleDiff = async (v1: string, v2: string) => {
    if (!v1 || !v2 || v1 === v2) return;
    if (comparing) { setYamlDiff(null); setMetricsCompare(null); setComparing(false); return; }
    setComparing(true);
    setYamlDiff(null); setMetricsCompare(null);
    try {
      if (mode === "engineer") {
        const result = await diffContracts(agentId, v1, v2);
        setYamlDiff(result);
      } else {
        const result = await compareVersions(agentId, v1, v2);
        setMetricsCompare(result);
      }
    } catch (err) {
      console.error("Version compare failed:", err);
    } finally {
      setComparing(false);
    }
  };

  const handleSaveYaml = async (contractId: number, version: string) => {
    const yaml = editYaml[contractId];
    if (!yaml) return;
    setSaving(contractId); setSaveError(null);
    try {
      await updateContract(agentId, version, yaml);
      onRefresh();
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(null);
    }
  };

  const handleSuggestRule = async () => {
    if (!nlRuleText.trim()) return;
    setSuggesting(true); setNlError(null); setSuggestResult(null);
    try {
      const result = await suggestRule(agentId, nlRuleText.trim());
      setSuggestResult(result);
      // auto-target the first pending contract
      if (!nlTargetVersion && pending.length > 0) setNlTargetVersion(pending[0].version);
    } catch (err: unknown) {
      setNlError(err instanceof Error ? err.message : "Suggest failed");
    } finally {
      setSuggesting(false);
    }
  };

  const handleApplyRule = (snippet: string, contractId: number, currentYaml: string) => {
    const existing = editYaml[contractId] ?? currentYaml;
    setEditYaml((prev) => ({ ...prev, [contractId]: existing.trimEnd() + "\n" + snippet + "\n" }));
    setExpandedYaml(contractId);
    setSuggestResult(null);
    setNlRuleText("");
  };

  return (
    <Panel>
      <PanelHeader
        title={`Contracts · ${contracts.length} version${contracts.length !== 1 ? "s" : ""}`}
        right={
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              padding: "3px 10px",
              background: generating ? "var(--bg-4)" : "var(--amber-glow)",
              border: "1px solid rgba(245,158,11,0.3)",
              borderRadius: "var(--radius-sm)",
              color: "var(--amber)",
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              cursor: generating ? "wait" : "pointer",
              letterSpacing: "0.04em",
            }}
          >
            {generating ? "GENERATING…" : "+ GENERATE PROPOSAL"}
          </button>
        }
      />

      <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
        {/* Active contract */}
        {active && (
          <div style={{
            padding: "10px 12px",
            background: "rgba(34,197,94,0.05)",
            border: "1px solid rgba(34,197,94,0.2)",
            borderRadius: "var(--radius-sm)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: "10px", color: "var(--green)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
                  ● ACTIVE
                </span>
                <span style={{ fontSize: "12px", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                  v{active.version}
                </span>
              </div>
              <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                Approved by {active.approved_by ?? "—"} · {formatLocalTimestamp(active.activated_at)}
              </span>
            </div>
            {active.summary_text && (
              <p style={{
                margin: "0 0 8px",
                fontSize: "11px",
                color: "var(--text-secondary)",
                fontFamily: "var(--font-sans)",
                lineHeight: 1.6,
                padding: "7px 10px",
                background: "rgba(34,197,94,0.04)",
                border: "1px solid rgba(34,197,94,0.12)",
                borderRadius: "var(--radius-sm)",
              }}>
                {active.summary_text}
              </p>
            )}
            <button
              onClick={() => setExpandedYaml(expandedYaml === active.id ? null : active.id)}
              style={{
                all: "unset",
                cursor: "pointer",
                fontSize: "10px",
                color: "var(--amber)",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.04em",
              }}
            >
              {expandedYaml === active.id ? "▾ HIDE YAML" : "▸ VIEW YAML"}
            </button>
            {expandedYaml === active.id && (
              <pre style={{
                marginTop: 8,
                padding: "10px",
                background: "var(--bg-1)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                fontSize: "11px",
                color: "var(--text-secondary)",
                fontFamily: "var(--font-mono)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: 300,
                overflowY: "auto",
              }}>
                {active.yaml_content}
              </pre>
            )}
          </div>
        )}

        {/* Pending contract (latest only) */}
        {latestPending && (() => {
          const c = latestPending;
          return (
            <div
              key={c.id}
              style={{
                padding: "10px 12px",
                background: "rgba(245,158,11,0.04)",
                border: "1px solid rgba(245,158,11,0.15)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: "10px", color: "var(--amber)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
                    ○ PENDING
                  </span>
                  <span style={{ fontSize: "12px", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                    v{c.version}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    onClick={() => setExpandedYaml(expandedYaml === c.id ? null : c.id)}
                    style={{
                      padding: "2px 8px",
                      background: "transparent",
                      border: "1px solid var(--border-default)",
                      borderRadius: "var(--radius-sm)",
                      color: "var(--text-secondary)",
                      fontSize: "10px",
                      fontFamily: "var(--font-mono)",
                      cursor: "pointer",
                      letterSpacing: "0.04em",
                    }}
                  >
                    YAML
                  </button>
                  <button
                    onClick={() => handleApprove(c.version)}
                    disabled={approving === c.version}
                    style={{
                      padding: "2px 8px",
                      background: approving === c.version ? "var(--bg-4)" : "var(--green)",
                      border: "none",
                      borderRadius: "var(--radius-sm)",
                      color: "#fff",
                      fontSize: "10px",
                      fontFamily: "var(--font-mono)",
                      cursor: approving === c.version ? "wait" : "pointer",
                      letterSpacing: "0.04em",
                      fontWeight: 600,
                    }}
                  >
                    {approving === c.version ? "APPROVING…" : "APPROVE"}
                  </button>
                  <button
                    onClick={() => handleDisapprove(c.version)}
                    disabled={disapproving === c.version}
                    style={{
                      padding: "2px 8px",
                      background: "transparent",
                      border: "1px solid rgba(239,68,68,0.35)",
                      borderRadius: "var(--radius-sm)",
                      color: "var(--red)",
                      fontSize: "10px",
                      fontFamily: "var(--font-mono)",
                      cursor: disapproving === c.version ? "wait" : "pointer",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {disapproving === c.version ? "REJECTING…" : "DISAPPROVE"}
                  </button>
                </div>
              </div>

              {c.summary_text && (
                <p style={{
                  margin: "0 0 8px",
                  fontSize: "11px",
                  color: "var(--text-secondary)",
                  fontFamily: "var(--font-sans)",
                  lineHeight: 1.6,
                  padding: "7px 10px",
                  background: "rgba(245,158,11,0.04)",
                  border: "1px solid rgba(245,158,11,0.10)",
                  borderRadius: "var(--radius-sm)",
                }}>
                  {c.summary_text}
                </p>
              )}

              {/* Meta labels — shown for last-generated contract */}
              {lastMeta && (
                <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 6 }}>
                  {lastMeta.requires_input.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                      <span style={{ fontSize: "11px", color: "var(--red)", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>REVIEW REQUIRED:</span>
                      {lastMeta.requires_input.map((item) => (
                        <span key={item} style={{
                          fontSize: "11px",
                          padding: "1px 5px",
                          background: "rgba(239,68,68,0.1)",
                          border: "1px solid rgba(239,68,68,0.2)",
                          borderRadius: "var(--radius-sm)",
                          color: "var(--red)",
                          fontFamily: "var(--font-mono)",
                        }}>
                          {item}
                        </span>
                      ))}
                    </div>
                  )}
                  {lastMeta.inferred.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                      <span style={{ fontSize: "11px", color: "var(--blue)", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>INFERRED:</span>
                      {lastMeta.inferred.map((item) => (
                        <span key={item} style={{
                          fontSize: "11px",
                          padding: "1px 5px",
                          background: "rgba(96,165,250,0.1)",
                          border: "1px solid rgba(96,165,250,0.2)",
                          borderRadius: "var(--radius-sm)",
                          color: "var(--blue)",
                          fontFamily: "var(--font-mono)",
                        }}>
                          {item}
                        </span>
                      ))}
                    </div>
                  )}
                  {lastMeta.assumed.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                      <span style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>DEFAULTS:</span>
                      {lastMeta.assumed.map((item) => (
                        <span key={item} style={{
                          fontSize: "11px",
                          padding: "1px 5px",
                          background: "var(--bg-4)",
                          borderRadius: "var(--radius-sm)",
                          color: "var(--text-dim)",
                          fontFamily: "var(--font-mono)",
                        }}>
                          {item}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {expandedYaml === c.id && (
                <div style={{ marginTop: 8 }}>
                  <textarea
                    value={editYaml[c.id] ?? c.yaml_content}
                    onChange={(e) => setEditYaml((prev) => ({ ...prev, [c.id]: e.target.value }))}
                    onFocus={() => { if (editYaml[c.id] === undefined) setEditYaml((prev) => ({ ...prev, [c.id]: c.yaml_content })); }}
                    spellCheck={false}
                    style={{
                      width: "100%",
                      minHeight: 220,
                      maxHeight: 380,
                      padding: "10px",
                      background: "var(--bg-1)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "11px",
                      color: "var(--text-secondary)",
                      fontFamily: "var(--font-mono)",
                      resize: "vertical",
                      outline: "none",
                      boxSizing: "border-box",
                      display: "block",
                    }}
                  />
                  {saveError && (
                    <div style={{ marginTop: 4, fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{saveError}</div>
                  )}
                  <div style={{ marginTop: 6, display: "flex", gap: 6, justifyContent: "flex-end" }}>
                    <button
                      onClick={() => { setEditYaml((prev) => { const n = { ...prev }; delete n[c.id]; return n; }); setSaveError(null); }}
                      style={{ padding: "3px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-mono)", cursor: "pointer" }}
                    >
                      RESET
                    </button>
                    <button
                      onClick={() => handleSaveYaml(c.id, c.version)}
                      disabled={saving === c.id || !editYaml[c.id] || editYaml[c.id] === c.yaml_content}
                      style={{ padding: "3px 12px", background: saving === c.id ? "var(--bg-4)" : "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: "var(--radius-sm)", color: "var(--green)", fontSize: 11, fontFamily: "var(--font-mono)", cursor: saving === c.id ? "wait" : "pointer", fontWeight: 700, letterSpacing: "0.05em" }}
                    >
                      {saving === c.id ? "SAVING…" : "SAVE CHANGES"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })()}

        {pending.length > 1 && (
          <div style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            {pending.length - 1} older pending version{pending.length - 1 !== 1 ? "s" : ""} hidden.
          </div>
        )}

        {/* Version comparison — version selects + YAML diff (engineer) or metrics (VP) */}
        {allVersions.length >= 2 && (
          <div style={{ marginTop: 8, paddingTop: 12, borderTop: "1px solid var(--border-subtle)" }}>
            {/* Controls row */}
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Compare
              </span>
              <select
                value={diffV1}
                onChange={(e) => { setDiffV1(e.target.value); setYamlDiff(null); setMetricsCompare(null); }}
                style={{
                  padding: "2px 6px",
                  background: "var(--bg-2)",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  cursor: "pointer",
                }}
              >
                <option value="">-- v1 --</option>
                {allVersions.map((v) => (
                  <option key={v} value={v}>v{v}</option>
                ))}
              </select>
              <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>vs</span>
              <select
                value={diffV2}
                onChange={(e) => { setDiffV2(e.target.value); setYamlDiff(null); setMetricsCompare(null); }}
                style={{
                  padding: "2px 6px",
                  background: "var(--bg-2)",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  cursor: "pointer",
                }}
              >
                <option value="">-- v2 --</option>
                {allVersions.map((v) => (
                  <option key={v} value={v}>v{v}</option>
                ))}
              </select>
              <button
                onClick={() => handleDiff(diffV1, diffV2)}
                disabled={!diffV1 || !diffV2 || diffV1 === diffV2 || comparing}
                style={{
                  padding: "2px 10px",
                  background: "transparent",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  color: (!diffV1 || !diffV2 || diffV1 === diffV2) ? "var(--text-dim)" : "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  cursor: (!diffV1 || !diffV2 || diffV1 === diffV2) ? "not-allowed" : "pointer",
                  letterSpacing: "0.04em",
                }}
              >
                {comparing ? "…" : "DIFF"}
              </button>
              {(yamlDiff || metricsCompare) && (
                <button
                  onClick={() => { setYamlDiff(null); setMetricsCompare(null); }}
                  style={{
                    padding: "2px 8px",
                    background: "transparent",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-sm)",
                    color: "var(--text-dim)",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    cursor: "pointer",
                  }}
                >
                  CLEAR
                </button>
              )}
            </div>

            {/* Engineer mode: YAML line-by-line diff */}
            {mode === "engineer" && yamlDiff && (
              <div style={{ marginTop: 8, border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", overflow: "hidden" }}>
                {/* Header */}
                <div style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "6px 10px",
                  background: "var(--bg-2)",
                  borderBottom: "1px solid var(--border-subtle)",
                }}>
                  <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
                    v{yamlDiff.v1.version} → v{yamlDiff.v2.version}
                  </span>
                  <span style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: yamlDiff.n_fields_changed === 0 ? "var(--green)" : "var(--amber)",
                    letterSpacing: "0.04em",
                  }}>
                    {yamlDiff.n_fields_changed === 0 ? "no changes" : `${yamlDiff.n_fields_changed} field${yamlDiff.n_fields_changed !== 1 ? "s" : ""} changed`}
                  </span>
                </div>
                {/* Diff body */}
                <div style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  lineHeight: 1.5,
                  maxHeight: 320,
                  overflowY: "auto",
                  background: "var(--bg-1)",
                }}>
                  {computeYamlDiff(yamlDiff.v1.yaml, yamlDiff.v2.yaml).map((line, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "0 10px",
                        background: line.op === "ins"
                          ? "rgba(34,197,94,0.08)"
                          : line.op === "del"
                            ? "rgba(239,68,68,0.08)"
                            : "transparent",
                        color: line.op === "ins"
                          ? "var(--green)"
                          : line.op === "del"
                            ? "var(--red)"
                            : "var(--text-dim)",
                        whiteSpace: "pre",
                      }}
                    >
                      {line.op === "ins" ? "+ " : line.op === "del" ? "- " : "  "}{line.text}
                    </div>
                  ))}
                </div>
                {/* Changed fields summary */}
                {yamlDiff.changes.length > 0 && (
                  <div style={{
                    padding: "6px 10px",
                    background: "var(--bg-2)",
                    borderTop: "1px solid var(--border-subtle)",
                  }}>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", marginBottom: 4 }}>
                      CHANGED FIELDS
                    </div>
                    {yamlDiff.changes.map((ch, i) => (
                      <div key={i} style={{ fontSize: 11, fontFamily: "var(--font-mono)", display: "flex", gap: 6, padding: "1px 0" }}>
                        <span style={{ color: "var(--amber)", minWidth: 140 }}>{ch.field}</span>
                        <span style={{ color: "var(--red)" }}>{String(ch.v1_value ?? "—")}</span>
                        <span style={{ color: "var(--text-dim)" }}>→</span>
                        <span style={{ color: "var(--green)" }}>{String(ch.v2_value ?? "—")}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* VP mode: metrics comparison grid */}
            {mode === "vp" && metricsCompare && (
              <div style={{
                marginTop: 8,
                padding: "12px",
                background: "var(--bg-1)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
              }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                  {["v1_metrics", "v2_metrics"].map((key, idx) => {
                    const m = metricsCompare[key as "v1_metrics" | "v2_metrics"];
                    const version = idx === 0 ? metricsCompare.v1 : metricsCompare.v2;
                    return (
                      <div key={key}>
                        <div style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.06em", marginBottom: 6 }}>
                          VERSION {version}
                          {idx === 1 && metricsCompare.deltas && (
                            <span style={{ marginLeft: 6 }}>
                              {metricsCompare.deltas.quality !== null && (
                                <span style={{ color: metricsCompare.deltas.quality > 0 ? "var(--green)" : "var(--red)" }}>
                                  quality {metricsCompare.deltas.quality > 0 ? "+" : ""}{(metricsCompare.deltas.quality * 100).toFixed(1)}%
                                </span>
                              )}
                              {metricsCompare.deltas.cost !== null && (
                                <span style={{ color: metricsCompare.deltas.cost < 0 ? "var(--green)" : "var(--red)", marginLeft: 6 }}>
                                  cost {metricsCompare.deltas.cost > 0 ? "+" : ""}{(metricsCompare.deltas.cost * 100).toFixed(1)}%
                                </span>
                              )}
                            </span>
                          )}
                        </div>
                        {[
                          { label: "Runs", value: m.n_runs.toString() },
                          { label: "Success", value: m.n_successful.toString() },
                          { label: "Violations", value: m.violations.toString(), bad: m.violations > 0 },
                          { label: "Avg Quality", value: m.avg_quality !== null ? `${(m.avg_quality * 100).toFixed(0)}%` : "—" },
                          { label: "Avg Cost", value: m.avg_cost !== null ? `$${m.avg_cost.toFixed(4)}` : "—" },
                          { label: "Latency P50", value: m.latency_p50 !== null ? `${m.latency_p50}ms` : "—" },
                        ].map((row) => (
                          <div key={row.label} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                            <span style={{ color: "var(--text-dim)" }}>{row.label}</span>
                            <span style={{ color: row.bad ? "var(--red)" : "var(--text-primary)" }}>{row.value}</span>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
                {metricsCompare.note && (
                  <p style={{ marginTop: 8, fontSize: "10px", color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
                    ⚠ {metricsCompare.note}
                  </p>
                )}
                <p style={{ marginTop: 4, fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                  {metricsCompare.caveat}
                </p>
              </div>
            )}
          </div>
        )}

        {contracts.length === 0 && (
          <p style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            No contracts yet. Generate a proposal to get started.
          </p>
        )}

        {/* ── Natural-language rule suggester — shown when there are pending contracts ── */}
        {pending.length > 0 && (
          <div style={{ marginTop: 8, paddingTop: 12, borderTop: "1px solid var(--border-subtle)" }}>
            <div style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 8 }}>
              Add a rule in plain English
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                value={nlRuleText}
                onChange={(e) => setNlRuleText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !suggesting && handleSuggestRule()}
                placeholder='e.g. "deny access to data/confidential" or "max 5 tool calls"'
                style={{
                  flex: 1, padding: "7px 10px", background: "var(--bg-1)",
                  border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)",
                  color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none",
                }}
              />
              <button
                onClick={handleSuggestRule}
                disabled={suggesting || !nlRuleText.trim()}
                style={{ padding: "7px 12px", background: suggesting ? "var(--bg-4)" : "var(--amber-glow)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: "var(--radius-sm)", color: suggesting ? "var(--text-dim)" : "var(--amber)", fontSize: 10, fontFamily: "var(--font-mono)", cursor: suggesting || !nlRuleText.trim() ? "not-allowed" : "pointer", fontWeight: 700, letterSpacing: "0.05em", whiteSpace: "nowrap" as const }}
              >
                {suggesting ? "…" : "SUGGEST →"}
              </button>
            </div>
            {nlError && <div style={{ marginTop: 4, fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{nlError}</div>}
            {suggestResult && (
              <div style={{ marginTop: 8, padding: "10px 12px", background: "var(--bg-1)", border: "1px solid var(--border-accent)", borderRadius: "var(--radius-sm)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em" }}>suggested yaml</span>
                    <span style={{ fontSize: 11, padding: "1px 5px", background: suggestResult.confidence === "high" ? "rgba(34,197,94,0.12)" : "rgba(245,158,11,0.12)", border: `1px solid ${suggestResult.confidence === "high" ? "rgba(34,197,94,0.2)" : "rgba(245,158,11,0.2)"}`, borderRadius: "var(--radius-sm)", color: suggestResult.confidence === "high" ? "var(--green)" : "var(--amber)", fontFamily: "var(--font-mono)" }}>
                      {suggestResult.confidence.toUpperCase()} CONFIDENCE
                    </span>
                  </div>
                  <button onClick={() => setSuggestResult(null)} style={{ all: "unset", cursor: "pointer", fontSize: 11, color: "var(--text-dim)" }}>✕</button>
                </div>
                <pre style={{ margin: 0, fontSize: 11, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap" }}>{suggestResult.yaml_snippet}</pre>
                <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" as const }}>
                  {latestPending && (
                    <button
                      key={latestPending.id}
                      onClick={() => handleApplyRule(suggestResult.yaml_snippet, latestPending.id, latestPending.yaml_content)}
                      style={{ padding: "3px 10px", background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: "var(--radius-sm)", color: "var(--green)", fontSize: 11, fontFamily: "var(--font-mono)", cursor: "pointer", fontWeight: 700 }}
                    >
                      APPEND TO v{latestPending.version}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Violation / Audit Panel  ──────────────────────────────────────────────────

function ViolationPanel({
  violations,
  audit,
  focusRunId,
  onRefresh,
}: {
  violations: Violation[];
  audit: AuditLog | null;
  focusRunId?: number | null;
  onRefresh: () => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [showReviewed, setShowReviewed] = useState(false);
  const [reviewingId, setReviewingId] = useState<number | null>(null);
  const hasFocusedRow = typeof focusRunId === "number" && violations.some((v) => v.run_id === focusRunId);
  const unreviewed = violations.filter((v) => !v.review_status);
  const reviewed = violations.filter((v) => !!v.review_status);
  const activeViolations = showReviewed ? violations : unreviewed;
  const display = showAll ? activeViolations : activeViolations.slice(0, 10);

  const handleReview = async (violationId: number, decision: "acknowledged" | "dismissed_false_positive") => {
    setReviewingId(violationId);
    try {
      await reviewViolation(violationId, decision, "dashboard-user");
      onRefresh();
    } catch (err) {
      console.error("Failed to review violation:", err);
    } finally {
      setReviewingId(null);
    }
  };

  return (
    <Panel>
      <PanelHeader
        title={`Violations · ${unreviewed.length} open${reviewed.length > 0 ? ` · ${reviewed.length} reviewed` : ""}`}
        right={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {reviewed.length > 0 && (
              <button
                onClick={() => setShowReviewed((s) => !s)}
                style={{ all: "unset", cursor: "pointer", fontSize: "10px", color: showReviewed ? "var(--amber)" : "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}
              >
                {showReviewed ? "HIDE REVIEWED" : `SHOW REVIEWED (${reviewed.length})`}
              </button>
            )}
            {audit && audit.total_violations > 0 ? (
              <span style={{ fontSize: "10px", color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                {audit.total_violations} total
              </span>
            ) : (
              <span style={{ fontSize: "10px", color: "var(--green)", fontFamily: "var(--font-mono)" }}>
                clean record
              </span>
            )}
          </div>
        }
      />
      {violations.length === 0 ? (
        <div style={{ padding: "16px 14px", fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
          No violations recorded.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          {hasFocusedRow && (
            <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--border-subtle)", fontSize: "10px", color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
              Focused on pending-action run #{focusRunId}
            </div>
          )}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px", fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ background: "var(--bg-1)" }}>
                {["Policy Rule", "Action", "Type", "Blocked", "Run", "Time", "Review"].map((h) => (
                  <th key={h} style={{
                    padding: "5px 10px",
                    textAlign: "left",
                    fontSize: "11px",
                    color: "var(--text-dim)",
                    fontWeight: 400,
                    letterSpacing: "0.07em",
                    textTransform: "uppercase",
                    whiteSpace: "nowrap",
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {display.map((v, i) => {
                const isFocus = typeof focusRunId === "number" && v.run_id === focusRunId;
                return (
                  <tr key={v.id ?? i} style={{ borderTop: "1px solid var(--border-subtle)", background: isFocus ? "rgba(245,158,11,0.12)" : "transparent" }}>
                    <td style={{ padding: "7px 10px", color: "var(--red)" }}>{v.policy_rule}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-secondary)", maxWidth: 200, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {v.action_attempted}
                    </td>
                    <td style={{ padding: "7px 10px" }}>
                      <span style={{
                        padding: "1px 6px",
                        background: v.event_type === "pre_check" ? "var(--red-dim)" : "var(--amber-glow)",
                        color: v.event_type === "pre_check" ? "var(--red)" : "var(--amber)",
                        borderRadius: "var(--radius-sm)",
                        fontSize: "11px",
                        letterSpacing: "0.04em",
                      }}>
                        {v.event_type}
                      </span>
                    </td>
                    <td style={{ padding: "7px 10px", color: v.blocked ? "var(--red)" : "var(--amber)" }}>
                      {v.blocked ? "BLOCKED" : "AUDITED"}
                    </td>
                    <td style={{ padding: "7px 10px", color: "var(--text-dim)" }}>#{v.run_id ?? "—"}</td>
                    <td style={{ padding: "7px 10px", color: "var(--text-dim)", whiteSpace: "nowrap" }}>
                      {formatLocalTimestamp(v.timestamp)}
                    </td>
                    <td style={{ padding: "7px 10px" }}>
                      {v.review_status ? (
                        <span style={{
                          padding: "1px 6px",
                          background: v.review_status === "dismissed_false_positive" ? "rgba(96,165,250,0.12)" : "rgba(34,197,94,0.12)",
                          border: `1px solid ${v.review_status === "dismissed_false_positive" ? "rgba(96,165,250,0.3)" : "rgba(34,197,94,0.3)"}`,
                          borderRadius: "var(--radius-sm)",
                          color: v.review_status === "dismissed_false_positive" ? "var(--blue)" : "var(--green)",
                          fontSize: "11px",
                          fontFamily: "var(--font-mono)",
                          letterSpacing: "0.04em",
                        }}>
                          {v.review_status === "dismissed_false_positive" ? "FALSE POSITIVE" : "ACKNOWLEDGED"}
                        </span>
                      ) : (
                        <div style={{ display: "flex", gap: 4 }}>
                          <button
                            onClick={() => handleReview(v.id, "dismissed_false_positive")}
                            disabled={reviewingId === v.id}
                            style={{
                              padding: "1px 6px",
                              background: "transparent",
                              border: "1px solid rgba(96,165,250,0.35)",
                              borderRadius: "var(--radius-sm)",
                              color: "var(--blue)",
                              fontSize: "11px",
                              fontFamily: "var(--font-mono)",
                              cursor: reviewingId === v.id ? "wait" : "pointer",
                            }}
                          >
                            DISMISS
                          </button>
                          <button
                            onClick={() => handleReview(v.id, "acknowledged")}
                            disabled={reviewingId === v.id}
                            style={{
                              padding: "1px 6px",
                              background: "transparent",
                              border: "1px solid rgba(34,197,94,0.35)",
                              borderRadius: "var(--radius-sm)",
                              color: "var(--green)",
                              fontSize: "11px",
                              fontFamily: "var(--font-mono)",
                              cursor: reviewingId === v.id ? "wait" : "pointer",
                            }}
                          >
                            ACK
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {activeViolations.length > 10 && (
            <div style={{ padding: "8px 14px", borderTop: "1px solid var(--border-subtle)" }}>
              <button
                onClick={() => setShowAll(!showAll)}
                style={{
                  all: "unset",
                  cursor: "pointer",
                  fontSize: "10px",
                  color: "var(--amber)",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.04em",
                }}
              >
                {showAll ? "SHOW LESS" : `SHOW ALL ${activeViolations.length}`}
              </button>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// ─── Context Flow Panel ────────────────────────────────────────────────────────

function ContextFlowPanel({ routes }: { routes: ContextRoute[] }) {
  if (routes.length === 0) return null;

  const totalAvail = routes.reduce((s, r) => s + r.tokens_available, 0);
  const totalSent = routes.reduce((s, r) => s + r.tokens_sent, 0);
  const totalSavings = totalAvail > 0 ? ((totalAvail - totalSent) / totalAvail * 100).toFixed(0) : "0";

  return (
    <Panel>
      <PanelHeader
        title="Context Flow · Sub-agents"
        right={
          <span style={{ fontSize: "10px", color: "var(--green)", fontFamily: "var(--font-mono)" }}>
            ↓ {totalSavings}% total token savings
          </span>
        }
      />
      <div style={{ padding: "12px 14px" }}>
        {/* Flow visualization */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
          {routes.map((r) => {
            const util = r.utilization * 100;
            const savings = ((r.tokens_available - r.tokens_sent) / r.tokens_available * 100).toFixed(0);
            const wasteColor = util > 50 ? "var(--amber)" : util > 30 ? "var(--green)" : "var(--blue)";
            return (
              <div key={r.subagent} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {/* Subagent name */}
                <span style={{
                  width: 120,
                  fontSize: "11px",
                  color: "var(--text-primary)",
                  fontFamily: "var(--font-mono)",
                  textTransform: "capitalize",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}>
                  {r.subagent}
                </span>

                {/* Flow bar */}
                <div style={{ flex: 1, position: "relative" }}>
                  {/* Background (available) */}
                  <div style={{
                    height: 16,
                    background: "var(--bg-4)",
                    borderRadius: "var(--radius-sm)",
                    overflow: "hidden",
                    position: "relative",
                  }}>
                    {/* Sent (filled portion) */}
                    <div style={{
                      width: `${Math.min(util, 100)}%`,
                      height: "100%",
                      background: wasteColor,
                      opacity: 0.6,
                      transition: "width 0.3s ease",
                    }} />
                    {/* Label inside bar */}
                    <span style={{
                      position: "absolute",
                      right: 6,
                      top: "50%",
                      transform: "translateY(-50%)",
                      fontSize: "11px",
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-secondary)",
                      letterSpacing: "0.04em",
                    }}>
                      {r.tokens_sent.toLocaleString()} / {r.tokens_available.toLocaleString()}
                    </span>
                  </div>
                </div>

                {/* Utilization */}
                <span style={{ width: 40, fontSize: "11px", fontFamily: "var(--font-mono)", color: wasteColor, textAlign: "right" }}>
                  {util.toFixed(0)}%
                </span>

                {/* Savings */}
                <span style={{ width: 50, fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--green)", textAlign: "right" }}>
                  −{savings}%
                </span>
              </div>
            );
          })}
        </div>

        {/* Summary */}
        <div style={{
          padding: "8px 10px",
          background: "var(--bg-1)",
          borderRadius: "var(--radius-sm)",
          display: "flex",
          justifyContent: "space-between",
          fontSize: "10px",
          fontFamily: "var(--font-mono)",
          color: "var(--text-dim)",
        }}>
          <span>Total available: {totalAvail.toLocaleString()} tokens</span>
          <span>Total sent: {totalSent.toLocaleString()} tokens</span>
          <span style={{ color: "var(--green)" }}>Saved: {(totalAvail - totalSent).toLocaleString()} tokens ({totalSavings}%)</span>
        </div>
      </div>
    </Panel>
  );
}

// ─── Quality Rubric Panel ─────────────────────────────────────────────────────

function QualityRubricPanel() {
  const [rubric, setRubric] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getQualityRubric().then((r) => { setRubric(r); setDraft(r); }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const updated = await updateQualityRubric(draft);
      setRubric(updated);
      setDraft(updated);
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (rubric === null) {
    return (
      <div style={{ padding: "10px 14px", border: "1px dashed var(--border-subtle)", borderRadius: "var(--radius-sm)", fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
        Loading evaluation prompt…
      </div>
    );
  }

  return (
    <Panel>
      <PanelHeader
        title="LLM Judge Prompt"
        right={
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {saved && <span style={{ fontSize: 10, color: "var(--green)", fontFamily: "var(--font-mono)" }}>Saved</span>}
            {saveError && <span style={{ fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{saveError}</span>}
            {!editing ? (
              <button
                onClick={() => { setEditing(true); setDraft(rubric); }}
                style={{ padding: "3px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: "pointer", letterSpacing: "0.05em" }}
              >
                EDIT
              </button>
            ) : (
              <>
                <button
                  onClick={() => { setEditing(false); setDraft(rubric); setSaveError(null); }}
                  style={{ padding: "3px 10px", background: "transparent", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: "pointer" }}
                >
                  CANCEL
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  style={{ padding: "3px 10px", background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.35)", borderRadius: "var(--radius-sm)", color: "var(--green)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: saving ? "wait" : "pointer", fontWeight: 700, letterSpacing: "0.05em" }}
                >
                  {saving ? "SAVING…" : "SAVE"}
                </button>
              </>
            )}
          </div>
        }
      />
      <div style={{ padding: "12px 14px" }}>
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            style={{
              width: "100%",
              minHeight: 240,
              background: "var(--bg-1)",
              border: "1px solid var(--border-accent)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-primary)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.6,
              padding: "10px 12px",
              resize: "vertical",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        ) : (
          <pre style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.6, whiteSpace: "pre-wrap", background: "var(--bg-1)", padding: "10px 12px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)" }}>
            {rubric}
          </pre>
        )}
      </div>
    </Panel>
  );
}

// ─── Trust History Chart ───────────────────────────────────────────────────────

function TrustHistoryPanel({ agent, runs }: { agent: Agent; runs: RunRecord[] }) {
  // Build trust series from runs
  const ordered = [...runs].sort((a, b) => a.id - b.id);
  const series = ordered
    .filter((r) => r.trust_score_after !== null)
    .map((r) => ({ runId: r.id, score: r.trust_score_after!, status: r.completion_status }));

  if (series.length === 0 && agent.trust_history.length === 0) return null;

  const data = series.length > 0 ? series : agent.trust_history.map((t) => ({ runId: t.run, score: t.score, status: "success" }));
  const maxScore = Math.max(...data.map((d) => d.score), 1);
  const minScore = Math.min(...data.map((d) => d.score), 0);
  const range = maxScore - minScore || 1;

  const W = 600;
  const H = 100;
  const pad = 2;
  const plotW = W - pad * 2;
  const plotH = H - pad * 2;

  const points = data.map((d, i) => ({
    x: pad + (i / Math.max(data.length - 1, 1)) * plotW,
    y: pad + plotH - ((d.score - minScore) / range) * plotH,
    ...d,
  }));

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  // Tier threshold lines
  const thresholds = [
    { score: 0.60, label: "Standard", color: "var(--blue)" },
    { score: 0.80, label: "Trusted", color: "var(--green)" },
  ];

  return (
    <Panel>
      <PanelHeader
        title="Trust Trajectory"
        right={
          <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            {data.length} data points
          </span>
        }
      />
      <div style={{ padding: "12px 14px" }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 120 }}>
          {/* Threshold lines */}
          {thresholds.map((t) => {
            const y = pad + plotH - ((t.score - minScore) / range) * plotH;
            return (
              <g key={t.label}>
                <line x1={pad} y1={y} x2={W - pad} y2={y} stroke={t.color} strokeWidth={0.5} strokeDasharray="4,3" opacity={0.4} />
                <text x={W - pad - 2} y={y - 3} fill={t.color} fontSize={7} textAnchor="end" fontFamily="var(--font-mono)" opacity={0.6}>
                  {t.label} ({t.score})
                </text>
              </g>
            );
          })}

          {/* Line */}
          <path d={pathD} fill="none" stroke="var(--amber)" strokeWidth={1.5} opacity={0.8} />

          {/* Points */}
          {points.map((p, i) => (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={2.5}
              fill={p.status === "failed" ? "var(--red)" : "var(--amber)"}
              opacity={0.9}
            >
              <title>Run #{p.runId}: {p.score.toFixed(3)}</title>
            </circle>
          ))}
        </svg>
      </div>
    </Panel>
  );
}

// ─── Multi-Agent Run Tree ─────────────────────────────────────────────────────

function RunTreeNodeCard({ node, depth = 0 }: { node: RunTreeNode; depth?: number }) {
  const [expanded, setExpanded] = useState(depth === 0);
  const hasChildren = node.children && node.children.length > 0;
  const hasViolation = node.violations && node.violations.length > 0;
  const statusColor = node.completion_status === "success" ? "var(--green)" : "var(--red)";

  return (
    <div style={{ marginLeft: depth * 14 }}>
      <div
        style={{
          padding: "9px 12px",
          background: depth === 0 ? "var(--bg-2)" : "var(--bg-1)",
          border: `1px solid ${hasViolation ? "rgba(239,68,68,0.25)" : depth === 0 ? "var(--border-accent)" : "var(--border-subtle)"}`,
          borderRadius: "var(--radius-sm)",
          marginBottom: 4,
          cursor: hasChildren ? "pointer" : "default",
        }}
        onClick={() => hasChildren && setExpanded(!expanded)}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {hasChildren && (
              <span style={{ fontSize: 10, color: "var(--text-dim)", userSelect: "none" }}>
                {expanded ? "▾" : "▸"}
              </span>
            )}
            {depth > 0 && <span style={{ fontSize: 11, color: "var(--text-dim)" }}>└</span>}
            <span style={{ fontSize: 10, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
              {node.agent_id}
            </span>
            <span style={{ fontSize: 11, padding: "1px 5px", background: `${statusColor}18`, border: `1px solid ${statusColor}30`, borderRadius: "var(--radius-sm)", color: statusColor, fontFamily: "var(--font-mono)" }}>
              {node.completion_status}
            </span>
            {hasViolation && (
              <span style={{ fontSize: 11, padding: "1px 5px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-sm)", color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                {node.violations.length} violation{node.violations.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 14, fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            <span>#{node.id}</span>
            {node.quality_score != null && <span>q={node.quality_score.toFixed(3)}</span>}
            {node.trust_score_after != null && <span>t={node.trust_score_after.toFixed(3)}</span>}
            {node.latency_ms != null && <span>{node.latency_ms}ms</span>}
          </div>
        </div>
      </div>
      {expanded && hasChildren && (
        <div style={{ marginBottom: 4 }}>
          {node.children.map((child) => (
            <RunTreeNodeCard key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function OrchestratorRunTree({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [tree, setTree] = useState<RunTreeNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getRunTree(runId)
      .then((data) => {
        if (!cancelled) setTree(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message ?? "Failed to load tree");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <Panel>
      <PanelHeader
        title="Execution Tree"
        right={
          <button
            onClick={onClose}
            style={{ padding: "3px 10px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-mono)", cursor: "pointer" }}
          >
            CLOSE ✕
          </button>
        }
      />
      <div style={{ padding: "12px 14px" }}>
        {loading && <p style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>Loading tree…</p>}
        {error && <p style={{ fontSize: 11, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{error}</p>}
        {!loading && !error && tree && <RunTreeNodeCard node={tree} depth={0} />}
        {!loading && !error && !tree && (
          <p style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>No tree data found for run #{runId}.</p>
        )}
      </div>
    </Panel>
  );
}

// ─── Run Detail Drawer ─────────────────────────────────────────────────────────

const CHECK_LABELS_DRAWER: Record<string, string> = {
  output_length: "Output Length",
  error_keywords: "No Error Keywords",
  format_compliance: "Format Compliance",
  contract_scope: "Contract Scope",
};

function RunStepDrawer({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [run, setRun] = useState<RunRecord | null>(null);
  const [spans, setSpans] = useState<RunSpansResponse | null>(null);
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [tab, setTab] = useState<"spans" | "waterfall" | "quality">("spans");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getRun(runId), getRunSpans(runId), getRunMetrics(runId)])
      .then(([r, s, m]) => {
        if (!cancelled) { setRun(r); setSpans(s); setMetrics(m); }
      })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [runId]);

  const statusColors: Record<string, string> = { success: "var(--green)", failed: "var(--red)", timeout: "var(--amber)", escalated: "var(--blue)" };
  const statusColor = run ? (statusColors[run.completion_status] ?? "var(--text-dim)") : "var(--text-dim)";

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 200,
      display: "flex", alignItems: "flex-end", justifyContent: "flex-end",
      background: "rgba(0,0,0,0.55)", backdropFilter: "blur(4px)",
    }} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{
        width: 640, maxWidth: "100vw", height: "100%",
        background: "var(--bg-1)", borderLeft: "1px solid var(--border-accent)",
        display: "flex", flexDirection: "column",
      }}>
        {/* Header */}
        <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border-default)", flexShrink: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
                Run #{runId}
              </span>
              {run && (
                <span style={{ padding: "2px 8px", background: `${statusColor}18`, border: `1px solid ${statusColor}30`, borderRadius: "var(--radius-sm)", color: statusColor, fontSize: 10, fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  {run.completion_status}
                </span>
              )}
              {run?.violations && run.violations.length > 0 && (
                <span style={{ padding: "2px 8px", background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-sm)", color: "var(--red)", fontSize: 10, fontFamily: "var(--font-mono)" }}>
                  {run.violations.length} VIOLATION{run.violations.length > 1 ? "S" : ""}
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <a href={`/runs/${runId}`} style={{ fontSize: 11, color: "var(--amber)", fontFamily: "var(--font-mono)", textDecoration: "none" }}>full page →</a>
              <button onClick={onClose} style={{ all: "unset", cursor: "pointer", fontSize: 15, color: "var(--text-dim)", padding: "2px 6px" }}>✕</button>
            </div>
          </div>

          {/* Metrics — 2×4 grid */}
          {run && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6 }}>
              {[
                { label: "CONTRACT", value: run.contract_version ? `v${run.contract_version}` : "—" },
                { label: "QUALITY", value: run.quality_score !== null ? `${Math.round(run.quality_score * 100)}%` : "—", color: run.quality_score !== null ? (run.quality_score >= 0.8 ? "var(--green)" : run.quality_score >= 0.6 ? "var(--amber)" : "var(--red)") : undefined },
                { label: "TRUST AFTER", value: run.trust_score_after !== null ? run.trust_score_after.toFixed(3) : "—", color: "var(--blue)" },
                { label: "LATENCY", value: run.latency_ms !== null ? `${run.latency_ms}ms` : "—" },
                { label: "COST", value: run.cost_usd !== null ? `$${run.cost_usd.toFixed(4)}` : "—" },
                { label: "IN TOKENS", value: run.input_tokens !== null ? run.input_tokens.toLocaleString() : "—" },
                { label: "OUT TOKENS", value: run.output_tokens !== null ? run.output_tokens.toLocaleString() : "—" },
                { label: "TIME", value: run.timestamp ? new Date(run.timestamp).toLocaleTimeString() : "—" },
              ].map((m) => (
                <div key={m.label} style={{ padding: "6px 8px", background: "var(--bg-2)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)" }}>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.07em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{m.label}</div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: m.color ?? "var(--text-primary)", fontFamily: "var(--font-mono)", marginTop: 2 }}>{m.value}</div>
                </div>
              ))}
            </div>
          )}

          {/* Tabs */}
          <div style={{ display: "flex", gap: 4 }}>
            {(["spans", "waterfall", "quality"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} style={{
                padding: "3px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)",
                background: tab === t ? "var(--bg-4)" : "transparent",
                color: tab === t ? "var(--amber)" : "var(--text-dim)",
                fontSize: 11, fontFamily: "var(--font-mono)", cursor: "pointer", textTransform: "uppercase", letterSpacing: "0.05em",
              }}>{t === "spans" ? "SPAN TREE" : t === "waterfall" ? "WATERFALL" : "QUALITY"}</button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px 18px" }}>
          {loading && <p style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>Loading…</p>}
          {error && <p style={{ fontSize: 12, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{error}</p>}

          {!loading && !error && tab === "spans" && spans && <SpanTree roots={spans.tree} />}
          {!loading && !error && tab === "spans" && !spans?.tree?.length && (
            <p style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>No spans recorded for this run.</p>
          )}

          {!loading && !error && tab === "waterfall" && spans && <WaterfallTimeline spans={spans.spans} />}
          {!loading && !error && tab === "waterfall" && !spans?.spans?.length && (
            <p style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>No timing data for this run.</p>
          )}

          {!loading && !error && tab === "quality" && run && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* Score header */}
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Quality Score</span>
                  <span style={{ fontSize: 32, fontWeight: 700, fontFamily: "var(--font-mono)", color: run.quality_score !== null ? (run.quality_score >= 0.8 ? "var(--green)" : run.quality_score >= 0.6 ? "var(--amber)" : "var(--red)") : "var(--text-dim)" }}>
                    {run.quality_score !== null ? `${Math.round(run.quality_score * 100)}%` : "—"}
                  </span>
                </div>
                {metrics?.quality_metrics && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Source</span>
                    <span style={{ fontSize: 13, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                      {metrics.quality_metrics.avg_llm_quality_subscore != null ? "composite (LLM + rules)" : "deterministic"}
                    </span>
                  </div>
                )}
              </div>

              {/* Per-check breakdown */}
              {run.quality_breakdown && Object.keys(run.quality_breakdown).length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <span style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Check Breakdown</span>
                  {Object.entries(run.quality_breakdown).map(([key, val]) => {
                    if (key === "blocked") return null;
                    const pct = typeof val === "number" ? Math.round(val * 100) : 0;
                    const c = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)";
                    return (
                      <div key={key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", minWidth: 160 }}>{CHECK_LABELS_DRAWER[key] ?? key}</span>
                        <div style={{ flex: 1, height: 6, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ width: `${pct}%`, height: "100%", background: c, transition: "width 0.4s ease" }} />
                        </div>
                        <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: c, minWidth: 36, textAlign: "right" }}>{pct}%</span>
                      </div>
                    );
                  })}
                  {run.quality_breakdown.blocked && (
                    <div style={{ padding: "6px 10px", background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-sm)", fontSize: 12, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                      Run was blocked — quality score forced to 0
                    </div>
                  )}
                </div>
              )}

              {/* LLM Rationale */}
              {run.quality_rationale && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <span style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>LLM Evaluator Rationale</span>
                  <div style={{ padding: "12px 14px", background: "var(--bg-2)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.65, fontFamily: "var(--font-sans, var(--font-mono))", whiteSpace: "pre-wrap" }}>
                    {run.quality_rationale}
                  </div>
                </div>
              )}

              {!run.quality_breakdown && !run.quality_rationale && (
                <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                  No detailed quality breakdown available for this run. Quality breakdown and LLM rationale are recorded for runs where the research-team agent is executed with the quality scoring enabled.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Run Task Button + Modal ───────────────────────────────────────────────────

const FULL_RUN_PHASES = [
  { label: "Initializing agent…", detail: "Loading contract and tool registry" },
  { label: "Running enforcement checks…", detail: "Verifying tool ACL, data paths, PII constraints" },
  { label: "Executing workflow…", detail: "Agent dispatching tasks to sub-nodes" },
  { label: "Collecting spans…", detail: "Recording tool calls and LLM invocations" },
  { label: "Scoring quality…", detail: "Running LLM-as-judge evaluation" },
  { label: "Updating trust score…", detail: "Applying enforcement outcomes to agent trust" },
];

const STEP_RUN_PHASES = [
  { label: "Initializing…", detail: "Loading contract" },
  { label: "Running enforcement check…", detail: "Validating tool against contract" },
  { label: "Executing task…", detail: "Running agent step" },
  { label: "Recording trace…", detail: "Persisting span and trust delta" },
];

function RunTaskButton({ agentId, agentType, onComplete }: { agentId: string; agentType?: string; onComplete: () => void }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"step" | "full" | "llm">("step");
  const [running, setRunning] = useState(false);
  const [runPhaseIdx, setRunPhaseIdx] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [result, setResult] = useState<ExecuteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async (selectedMode: "step" | "full" | "llm") => {
    // If running full on an orchestrator, use true LLM mode to spawn subagents
    const actualMode = (selectedMode === "full" && agentType === "orchestrator") ? "llm" : selectedMode;
    const phases = (actualMode === "step") ? STEP_RUN_PHASES : FULL_RUN_PHASES;
    setMode(actualMode);
    setRunning(true);
    setRunPhaseIdx(0);
    setElapsedMs(0);
    setError(null);
    setResult(null);

    // Phase ticker — advances through phases and tracks elapsed time
    const startTime = Date.now();
    const phaseInterval = setInterval(() => {
      setElapsedMs(Date.now() - startTime);
      setRunPhaseIdx((prev) => Math.min(prev + 1, phases.length - 2));
    }, actualMode === "step" ? 600 : 1800);

    try {
      const res = await executeAgent(agentId, actualMode);
      clearInterval(phaseInterval);
      setRunPhaseIdx(phases.length - 1);
      setElapsedMs(Date.now() - startTime);
      setResult(res);
      onComplete();
    } catch (err) {
      clearInterval(phaseInterval);
      setError(err instanceof Error ? err.message : "Execution failed");
    } finally {
      setRunning(false);
    }
  };

  const handleResume = async () => {
    try {
      setRunning(true);
      setError(null);
      await resumeAgent(agentId);
      // Wait a bit, then automatically retry the run
      const res = await executeAgent(agentId, mode);
      setResult(res);
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resume failed");
    } finally {
      setRunning(false);
    }
  };

  const handleClose = () => {
    setOpen(false);
    setResult(null);
    setError(null);
  };

  const stepResult = result && result.mode === "step" ? (result as ExecuteStepResult) : null;
  const fullResult = result && result.mode === "full" ? (result as ExecuteFullResult) : null;
  const llmResult = result && result.mode === "llm" ? (result as ExecuteLLMResult) : null;
  const pausedResult = result && result.mode === "paused" ? (result as ExecutePausedResult) : null;

  return (
    <>
      <div style={{ display: "flex", gap: 4 }}>
        <button
          onClick={() => setOpen(true)}
          style={{
            padding: "4px 12px",
            background: "var(--amber-glow)",
            border: "1px solid rgba(245,158,11,0.35)",
            borderRadius: "var(--radius-sm)",
            color: "var(--amber)",
            fontSize: "10px",
            fontFamily: "var(--font-mono)",
            cursor: "pointer",
            letterSpacing: "0.06em",
            fontWeight: 600,
          }}
        >
          ▶ RUN TASK
        </button>
      </div>

      {open && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 200,
            background: "rgba(0,0,0,0.65)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
        >
          <div style={{
            width: fullResult ? 620 : 520,
            maxHeight: "85vh",
            overflowY: "auto",
            background: "var(--bg-2)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            padding: "20px 24px",
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}>
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: "13px", fontWeight: 700, color: "var(--amber)", letterSpacing: "0.08em" }}>
                  {pausedResult ? "HUMAN APPROVAL REQUIRED" : fullResult ? "FULL RUN COMPLETE" : llmResult ? "LLM RUN COMPLETE" : "RUN TASK"}
                </span>
                {result && !pausedResult && (
                  <span style={{ fontSize: 11, padding: "1px 6px", background: result.mode === "full" || result.mode === "llm" ? "rgba(99,102,241,0.12)" : "var(--amber-glow)", border: `1px solid ${result.mode === "full" || result.mode === "llm" ? "rgba(99,102,241,0.3)" : "rgba(245,158,11,0.2)"}`, borderRadius: "var(--radius-sm)", color: result.mode === "full" || result.mode === "llm" ? "#818cf8" : "var(--amber)", fontFamily: "var(--font-mono)" }}>
                    {result.mode === "step" ? "STEP" : result.mode === "llm" ? "LLM" : "FULL WORKFLOW"}
                  </span>
                )}
              </div>
              <button onClick={handleClose} style={{ all: "unset", cursor: "pointer", fontSize: "16px", color: "var(--text-dim)", lineHeight: 1 }}>✕</button>
            </div>

            {/* Info */}
            {!result && !running && !error && (
              <p style={{ fontSize: "11px", color: "var(--text-secondary)", fontFamily: "var(--font-sans)", fontWeight: 300, lineHeight: 1.6, margin: 0 }}>
                Choose a run mode: <span style={{ color: "var(--amber)" }}>Step</span> executes one task with full detail. <span style={{ color: "#818cf8" }}>Full Workflow</span> runs all available tasks in sequence and summarizes the results.
              </p>
            )}

            {/* Agent ID */}
            {!result && (
              <div style={{ padding: "8px 12px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", fontSize: "10px", fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                agent: <span style={{ color: "var(--text-primary)" }}>{agentId}</span>
              </div>
            )}

            {running && (() => {
              const phases = mode === "step" ? STEP_RUN_PHASES : FULL_RUN_PHASES;
              const phase = phases[Math.min(runPhaseIdx, phases.length - 1)];
              const elapsed = (elapsedMs / 1000).toFixed(1);
              return (
                <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "4px 0" }}>
                  {/* Elapsed + current phase */}
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ animation: "spin 1s linear infinite", display: "inline-block", color: "var(--amber)", fontSize: 16 }}>◌</span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: 13, color: "var(--amber)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{phase.label}</span>
                      <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{phase.detail}</span>
                    </div>
                    <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{elapsed}s</span>
                  </div>
                  {/* Phase progress dots */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {phases.map((p, i) => {
                      const done = i < runPhaseIdx;
                      const active = i === runPhaseIdx;
                      return (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, opacity: done ? 0.5 : active ? 1 : 0.3 }}>
                          <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: done ? "var(--green)" : active ? "var(--amber)" : "var(--text-dim)", minWidth: 14 }}>
                            {done ? "✓" : active ? "›" : "·"}
                          </span>
                          <span style={{ fontSize: 12, color: done ? "var(--green)" : active ? "var(--text-primary)" : "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                            {p.label}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}

            {error && (
              <div style={{ padding: "10px 12px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "var(--radius-sm)", fontSize: "11px", color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                {error}
              </div>
            )}

            {/* PAUSED RESULT (Human in the loop) */}
            {pausedResult && (
              <div style={{ padding: "12px 16px", background: "rgba(245,158,11,0.05)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: "var(--radius-sm)", display: "flex", flexDirection: "column", gap: 12 }}>
                <p style={{ margin: 0, fontSize: "12px", color: "var(--text-primary)", fontWeight: 500 }}>
                  Agent <strong>{pausedResult.agent_id}</strong> has paused execution.
                </p>
                <div style={{ padding: "8px 12px", background: "var(--bg-0)", borderRadius: "var(--radius-sm)", fontSize: "11px", color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                  {pausedResult.message}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                  <button
                    onClick={handleResume}
                    style={{
                      padding: "6px 14px",
                      background: "rgba(34,197,94,0.15)",
                      border: "1px solid rgba(34,197,94,0.4)",
                      borderRadius: "var(--radius-sm)",
                      color: "var(--green)",
                      fontSize: "10px",
                      fontWeight: 700,
                      cursor: "pointer",
                      letterSpacing: "0.05em",
                    }}
                  >
                    AUTHORIZE & RESUME
                  </button>
                  <button
                    onClick={handleClose}
                    style={{
                      padding: "6px 14px",
                      background: "transparent",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      color: "var(--text-secondary)",
                      fontSize: "10px",
                      cursor: "pointer",
                      letterSpacing: "0.05em",
                    }}
                  >
                    ABORT
                  </button>
                </div>
              </div>
            )}

            {/* STEP RESULT */}
            {stepResult && (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ padding: "3px 10px", borderRadius: "var(--radius-sm)", fontSize: "10px", fontWeight: 700, letterSpacing: "0.08em", background: stepResult.blocked ? "rgba(239,68,68,0.12)" : "rgba(34,197,94,0.12)", color: stepResult.blocked ? "var(--red)" : "var(--green)", border: `1px solid ${stepResult.blocked ? "rgba(239,68,68,0.3)" : "rgba(34,197,94,0.3)"}` }}>
                    {stepResult.blocked ? "BLOCKED" : "ALLOWED"}
                  </span>
                  <span style={{ padding: "3px 10px", borderRadius: "var(--radius-sm)", fontSize: "10px", letterSpacing: "0.06em", background: stepResult.trust_delta >= 0 ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)", color: stepResult.trust_delta >= 0 ? "var(--green)" : "var(--red)", border: `1px solid ${stepResult.trust_delta >= 0 ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`, fontFamily: "var(--font-mono)" }}>
                    {stepResult.trust_delta >= 0 ? "+" : ""}{stepResult.trust_delta.toFixed(4)} trust
                  </span>
                  <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginLeft: "auto" }}>
                    task {stepResult.task_index + 1} / {stepResult.total_tasks}
                  </span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  {([
                    ["Tool", stepResult.tool],
                    ["Trust before", stepResult.trust_before.toFixed(4)],
                    ["Trust after", stepResult.trust_after.toFixed(4)],
                    ["Quality", stepResult.quality_score !== null ? stepResult.quality_score.toFixed(2) : "—"],
                    ["Cost", `$${stepResult.cost_usd.toFixed(4)}`],
                    ["Tokens", `${(stepResult.token_counts?.input ?? 0) + (stepResult.token_counts?.output ?? 0)}`],
                  ] as [string, string][]).map(([label, val]) => (
                    <div key={label} style={{ padding: "6px 10px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</span>
                      <span style={{ fontSize: "11px", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{val}</span>
                    </div>
                  ))}
                </div>
                <div style={{ padding: "8px 12px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-sans)", fontWeight: 300, lineHeight: 1.5 }}>
                  <span style={{ color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>task: </span>{stepResult.task_description}
                </div>
                <div style={{ padding: "10px 12px", background: "var(--bg-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap", maxHeight: 160, overflowY: "auto", lineHeight: 1.5 }}>
                  {stepResult.output || "(no output)"}
                </div>
                <p style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", margin: 0 }}>{stepResult.note}</p>
              </div>
            )}

            {/* FULL RESULT */}
            {fullResult && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {/* Summary bar */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
                  {([
                    ["Tasks", `${fullResult.total_tasks}`],
                    ["Trust Δ", `${fullResult.trust_delta >= 0 ? "+" : ""}${fullResult.trust_delta.toFixed(4)}`],
                    ["Violations", `${fullResult.violations}`],
                    ["Trust end", fullResult.trust_end.toFixed(4)],
                  ] as [string, string][]).map(([label, val]) => (
                    <div key={label} style={{ padding: "8px 10px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</span>
                      <span style={{ fontSize: "13px", fontWeight: 700, color: label === "Violations" && fullResult.violations > 0 ? "var(--red)" : label === "Trust Δ" && fullResult.trust_delta < 0 ? "var(--red)" : "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{val}</span>
                    </div>
                  ))}
                </div>
                {/* Step list — hidden */}
                <p style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", margin: 0 }}>{fullResult.note}</p>
              </div>
            )}

            {/* LLM RESULT */}
            {llmResult && (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ padding: "3px 10px", borderRadius: "var(--radius-sm)", fontSize: "10px", fontWeight: 700, letterSpacing: "0.08em", background: llmResult.blocked ? "rgba(239,68,68,0.12)" : "rgba(34,197,94,0.12)", color: llmResult.blocked ? "var(--red)" : "var(--green)", border: `1px solid ${llmResult.blocked ? "rgba(239,68,68,0.3)" : "rgba(34,197,94,0.3)"}` }}>
                    {llmResult.blocked ? "BLOCKED" : "ALLOWED"}
                  </span>
                  <span style={{ padding: "3px 10px", borderRadius: "var(--radius-sm)", fontSize: "10px", letterSpacing: "0.06em", background: llmResult.trust_delta >= 0 ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)", color: llmResult.trust_delta >= 0 ? "var(--green)" : "var(--red)", border: `1px solid ${llmResult.trust_delta >= 0 ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`, fontFamily: "var(--font-mono)" }}>
                    {llmResult.trust_delta >= 0 ? "+" : ""}{llmResult.trust_delta.toFixed(4)} trust
                  </span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  {([
                    ["Trust before", llmResult.trust_before.toFixed(4)],
                    ["Trust after", llmResult.trust_after.toFixed(4)],
                    ["Quality", llmResult.quality_score != null ? llmResult.quality_score.toFixed(3) : "—"],
                    ["Cost", `$${llmResult.cost_usd.toFixed(4)}`],
                    ["Input tokens", `${llmResult.token_counts.input}`],
                    ["Output tokens", `${llmResult.token_counts.output}`],
                  ] as [string, string][]).map(([label, val]) => (
                    <div key={label} style={{ padding: "6px 10px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</span>
                      <span style={{ fontSize: "11px", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{val}</span>
                    </div>
                  ))}
                </div>
                <div style={{ padding: "8px 12px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-sans)", fontWeight: 300, lineHeight: 1.5 }}>
                  <span style={{ color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>input: </span>{llmResult.input}
                </div>
                <div style={{ padding: "10px 12px", background: "var(--bg-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", fontSize: "10px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap", maxHeight: 200, overflowY: "auto", lineHeight: 1.5 }}>
                  {llmResult.output || "(no output)"}
                </div>
                {llmResult.note && <p style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", margin: 0 }}>{llmResult.note}</p>}
              </div>
            )}

            {/* Mode selector + Actions */}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
              {!result ? (
                <>
                  <button onClick={handleClose} style={{ padding: "6px 14px", background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: "pointer", letterSpacing: "0.06em" }}>
                    CANCEL
                  </button>
                  <button onClick={() => handleRun("step")} disabled={running} style={{ padding: "6px 14px", background: "var(--amber-glow)", border: "1px solid rgba(245,158,11,0.35)", borderRadius: "var(--radius-sm)", color: "var(--amber)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: running ? "wait" : "pointer", letterSpacing: "0.06em", fontWeight: 700 }}>
                    {running && mode === "step" ? "RUNNING…" : "▶ STEP"}
                  </button>
                  <button onClick={() => handleRun("full")} disabled={running} style={{ padding: "6px 14px", background: "rgba(99,102,241,0.12)", border: "1px solid rgba(99,102,241,0.35)", borderRadius: "var(--radius-sm)", color: "#818cf8", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: running ? "wait" : "pointer", letterSpacing: "0.06em", fontWeight: 700 }}>
                    {running && (mode === "full" || mode === "llm") ? "RUNNING…" : "▶▶ RUN ALL"}
                  </button>
                </>
              ) : (
                <>
                  <button onClick={handleClose} style={{ padding: "6px 14px", background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: "pointer", letterSpacing: "0.06em" }}>
                    CLOSE
                  </button>
                  <button onClick={() => handleRun("step")} disabled={running} style={{ padding: "6px 14px", background: "var(--amber-glow)", border: "1px solid rgba(245,158,11,0.35)", borderRadius: "var(--radius-sm)", color: "var(--amber)", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: running ? "wait" : "pointer", letterSpacing: "0.06em", fontWeight: 700 }}>
                    ▶ STEP AGAIN
                  </button>
                  <button onClick={() => handleRun("full")} disabled={running} style={{ padding: "6px 14px", background: "rgba(99,102,241,0.12)", border: "1px solid rgba(99,102,241,0.35)", borderRadius: "var(--radius-sm)", color: "#818cf8", fontSize: "10px", fontFamily: "var(--font-mono)", cursor: running ? "wait" : "pointer", letterSpacing: "0.06em", fontWeight: 700 }}>
                    ▶▶ RUN ALL
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── Export Panel ──────────────────────────────────────────────────────────────

function ExportButton({ agentId }: { agentId: string }) {
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      const data = await exportCompliance(agentId);
      if (data) {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${agentId}-compliance-export.json`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      console.error("Export failed:", err);
    } finally {
      setExporting(false);
    }
  };

  return (
    <button
      onClick={handleExport}
      disabled={exporting}
      style={{
        padding: "4px 12px",
        background: "var(--bg-3)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--radius-sm)",
        color: "var(--text-secondary)",
        fontSize: "10px",
        fontFamily: "var(--font-mono)",
        cursor: exporting ? "wait" : "pointer",
        letterSpacing: "0.04em",
      }}
    >
      {exporting ? "EXPORTING…" : "↓ EXPORT COMPLIANCE"}
    </button>
  );
}

// ─── Main Agent Detail Page ────────────────────────────────────────────────────

export default function AgentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { mode } = useMode();
  const agentId = params.id as string;

  // State
  const [agent, setAgent] = useState<Agent | null>(null);
  const [metrics, setMetrics] = useState<AgentMetrics | null>(null);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [audit, setAudit] = useState<AuditLog | null>(null);
  const [contextRoutes, setContextRoutes] = useState<ContextRoute[]>([]);
  const [attributions, setAttributions] = useState<Attribution[]>([]);
  const [trends, setTrends] = useState<AgentMetricTrends | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [graphRefreshKey, setGraphRefreshKey] = useState(0);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [contractTab, setContractTab] = useState<"contract" | "eval">("contract");
  const [enfTab, setEnfTab] = useState<"violations" | "attribution">("violations");
  const [checkResult, setCheckResult] = useState<CheckChangesResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [treeRunId, setTreeRunId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const pendingRunMatch = (agent?.pending_action?.context ?? "").match(/run\s*#?(\d+)/i);
  const pendingRunId = pendingRunMatch ? Number(pendingRunMatch[1]) : null;

  const jumpToSection = (sectionId: string) => {
    const node = document.getElementById(sectionId);
    if (node) {
      node.scrollIntoView({ behavior: "smooth", block: "start" });
      window.history.replaceState(null, "", `#${sectionId}`);
    }
  };

  const handleDeleteAgent = async () => {
    if (!confirmDelete) { setConfirmDelete(true); return; }
    setDeleting(true);
    try {
      await deleteAgent(agentId);
      router.push("/");
    } catch (err) {
      console.error("Delete failed:", err);
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [ag, met, trendData, con, vio, aud, ctx, attrs, rns] = await Promise.all([
        getAgent(agentId),
        getMetrics(agentId),
        getAgentMetricTrends(agentId, 30, "run"),
        getContracts(agentId),
        getViolations(agentId),
        getAuditLog(agentId),
        getContextRoutes(agentId),
        getAttributions(agentId, 50, true),
        getRuns(agentId, 50),
      ]);
      if (ag) setAgent(ag);
      setMetrics(met);
      setTrends(trendData);
      setContracts(con);
      setViolations(vio);
      setAudit(aud);
      setContextRoutes(ctx);
      setAttributions(attrs);
      setRuns(rns);
    } catch (err) {
      console.error("Failed to load agent data:", err);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadData();
  }, [loadData, refreshKey]);

  const handleRefresh = () => { setRefreshKey((k) => k + 1); setGraphRefreshKey((k) => k + 1); };

  const handleCheckChanges = async () => {
    setChecking(true);
    try {
      const result = await checkAgentChanges(agentId);
      setCheckResult(result);
      if (result.changed) handleRefresh();
    } catch (err) {
      console.error("Check changes failed:", err);
    } finally {
      setChecking(false);
    }
  };

  // SSE: auto-refresh data when this agent's run completes or trust changes
  const { lastEvent } = useEventStream();
  useEffect(() => {
    if (!lastEvent) return;
    const data = lastEvent.data as Record<string, unknown>;
    if (
      (lastEvent.type === "run_completed" || lastEvent.type === "trust_changed") &&
      data.agent_id === agentId
    ) {
      handleRefresh();
    }
  }, [lastEvent, agentId]);

  if (loading && !agent) {
    return (
      <div style={{
        minHeight: "100vh",
        background: "var(--bg-0)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--text-dim)",
        fontFamily: "var(--font-mono)",
        fontSize: "12px",
      }}>
        Loading agent…
      </div>
    );
  }

  if (!agent) {
    return (
      <div style={{
        minHeight: "100vh",
        background: "var(--bg-0)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: 12,
        color: "var(--text-dim)",
        fontFamily: "var(--font-mono)",
      }}>
        <span style={{ fontSize: "14px" }}>Agent not found: {agentId}</span>
        <button
          onClick={() => router.push("/")}
          style={{
            padding: "4px 12px",
            background: "var(--amber-glow)",
            border: "1px solid rgba(245,158,11,0.3)",
            borderRadius: "var(--radius-sm)",
            color: "var(--amber)",
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            cursor: "pointer",
          }}
        >
          ← Back to Fleet
        </button>
      </div>
    );
  }

  const tierStyle = TIER[agent.tier];

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-0)", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
      {/* ── Top Bar ──────────────────────────────────────────────── */}
      <header style={{
        position: "sticky",
        top: 0,
        zIndex: 50,
        background: "var(--bg-0)",
        borderBottom: "1px solid var(--border-default)",
        padding: "0 24px",
        height: 48,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => router.push("/")}
            style={{
              all: "unset",
              cursor: "pointer",
              fontSize: "15px",
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--amber)",
            }}
          >
            NORMA
          </button>
          <span style={{ fontSize: "10px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>
            / <span
              onClick={() => router.push("/")}
              style={{ cursor: "pointer", color: "var(--text-dim)" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text-secondary)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-dim)")}
            >dashboard</span> / {agentId}
          </span>
          <Link
            href="/runs"
            style={{
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              color: "var(--text-dim)",
              textDecoration: "none",
              letterSpacing: "0.06em",
              marginLeft: 12,
            }}
          >
            log →
          </Link>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <RunTaskButton agentId={agentId} agentType={agent.type} onComplete={handleRefresh} />
          <button
            onClick={handleCheckChanges}
            disabled={checking}
            title="Re-hash agent files and detect code changes"
            style={{
              padding: "5px 10px",
              background: "transparent",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-sm)",
              color: checking ? "var(--text-dim)" : "var(--text-secondary)",
              fontSize: "10px",
              fontFamily: "var(--font-mono)",
              cursor: checking ? "wait" : "pointer",
              letterSpacing: "0.05em",
              whiteSpace: "nowrap",
            }}
          >
            {checking ? "CHECKING…" : "⟳ CHECK CODE"}
          </button>
          <ExportButton agentId={agentId} />
          {confirmDelete ? (
            <>
              <button
                onClick={handleDeleteAgent}
                disabled={deleting}
                style={{
                  padding: "5px 10px",
                  background: "rgba(239,68,68,0.15)",
                  border: "1px solid rgba(239,68,68,0.4)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--red)",
                  fontSize: "10px",
                  fontFamily: "var(--font-mono)",
                  cursor: deleting ? "wait" : "pointer",
                  letterSpacing: "0.05em",
                  fontWeight: 700,
                }}
              >
                {deleting ? "DELETING…" : "CONFIRM DELETE"}
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                style={{
                  padding: "5px 10px",
                  background: "transparent",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-dim)",
                  fontSize: "10px",
                  fontFamily: "var(--font-mono)",
                  cursor: "pointer",
                  letterSpacing: "0.05em",
                }}
              >
                CANCEL
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              title="Delete this agent and all its data"
              style={{
                padding: "5px 10px",
                background: "transparent",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-dim)",
                fontSize: "10px",
                fontFamily: "var(--font-mono)",
                cursor: "pointer",
                letterSpacing: "0.05em",
              }}
            >
              ✕ DELETE
            </button>
          )}
          <ModeToggle />
        </div>
      </header>

      {/* ── Content ──────────────────────────────────────────────── */}
      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 16 }}>

        {/* ── Agent Header ────────────────────────────────────────── */}
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          padding: "16px 20px",
          background: "var(--bg-2)",
          border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-md)",
        }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <span style={{ fontSize: "20px", fontWeight: 700, color: "var(--text-primary)" }}>
                {mode === "vp" ? agent.name : agent.id}
              </span>
              <span style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "2px 8px",
                background: tierStyle.bg,
                border: `1px solid ${tierStyle.text}30`,
                borderRadius: "var(--radius-sm)",
                color: tierStyle.text,
                fontSize: "10px",
                letterSpacing: "0.1em",
                textTransform: "capitalize",
                fontWeight: 500,
              }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: tierStyle.dot, boxShadow: `0 0 4px ${tierStyle.dot}` }} />
                {agent.tier}
              </span>
              {agent.pending_action && (
                <span style={{
                  padding: "2px 7px",
                  background: "var(--red-dim)",
                  border: "1px solid rgba(239,68,68,0.3)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--red)",
                  fontSize: "11px",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                }}>
                  {agent.pending_action.type.replace(/_/g, " ")}
                </span>
              )}
              {agent.code_status === "changed" && (
                <span style={{
                  padding: "2px 7px",
                  background: "rgba(245,158,11,0.1)",
                  border: "1px solid rgba(245,158,11,0.3)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--amber)",
                  fontSize: "11px",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                }}>
                  ⚠ CODE CHANGED
                </span>
              )}
              {agent.code_status === "missing" && (
                <span style={{
                  padding: "2px 7px",
                  background: "rgba(239,68,68,0.1)",
                  border: "1px solid rgba(239,68,68,0.3)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--red)",
                  fontSize: "11px",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                }}>
                  ✕ FILES MISSING
                </span>
              )}
              {checkResult && (
                <span style={{
                  padding: "2px 8px",
                  background: checkResult.status === "ok"
                    ? "rgba(34,197,94,0.08)"
                    : checkResult.status === "changed"
                      ? "rgba(245,158,11,0.08)"
                      : "rgba(239,68,68,0.08)",
                  border: `1px solid ${checkResult.status === "ok"
                    ? "rgba(34,197,94,0.3)"
                    : checkResult.status === "changed"
                      ? "rgba(245,158,11,0.3)"
                      : "rgba(239,68,68,0.3)"
                    }`,
                  borderRadius: "var(--radius-sm)",
                  color: checkResult.status === "ok"
                    ? "var(--green)"
                    : checkResult.status === "changed"
                      ? "var(--amber)"
                      : "var(--red)",
                  fontSize: "11px",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.04em",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                }}>
                  {checkResult.status === "ok"
                    ? `✓ unchanged · ${checkResult.files_checked.length} file${checkResult.files_checked.length !== 1 ? "s" : ""} · ${formatLocalTimestamp(checkResult.last_seen_at)}`
                    : checkResult.status === "changed"
                      ? `⚠ changed → v${checkResult.agent_code_version} · ${formatLocalTimestamp(checkResult.last_seen_at)}`
                      : `✕ files missing · ${formatLocalTimestamp(checkResult.last_seen_at)}`}
                </span>
              )}
            </div>
            <p style={{ fontSize: "12px", color: "var(--text-secondary)", fontFamily: "var(--font-sans)", fontWeight: 300, marginBottom: 8 }}>
              {agent.description}
            </p>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
                Contract <span style={{ color: "var(--text-secondary)" }}>v{agent.contract_version}</span>
              </span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
                Deployed <span style={{ color: "var(--text-secondary)" }}>{formatLocalTimestamp(agent.contract_deployed)}</span>
              </span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
                Approved by <span style={{ color: "var(--text-secondary)" }}>{agent.approved_by}</span>
              </span>
              <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
                Last run <span style={{ color: "var(--text-secondary)" }}>{formatLocalTimestamp(agent.last_run_at)}</span>
              </span>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            <span style={{ fontSize: "28px", fontWeight: 700, color: tierStyle.text, lineHeight: 1 }}>
              {agent.trust_score.toFixed(3)}
            </span>
            <span style={{ fontSize: "11px", color: "var(--text-dim)", letterSpacing: "0.06em" }}>TRUST SCORE</span>
            <TrustSparkline data={agent.trust_history} width={140} height={30} />
          </div>
        </div>

        {/* ── Pending Action Banner ───────────────────────────────── */}
        {agent.pending_action && (
          <div style={{
            padding: "12px 16px",
            background: "rgba(239,68,68,0.06)",
            border: "1px solid rgba(239,68,68,0.2)",
            borderRadius: "var(--radius-sm)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}>
            <div>
              <p style={{ fontSize: "12px", color: "#fca5a5", fontFamily: "var(--font-sans)", fontWeight: 300, lineHeight: 1.5, margin: 0 }}>
                {agent.pending_action.message}
              </p>
              {agent.pending_action.context && (
                <p style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", margin: "4px 0 0" }}>
                  {agent.pending_action.context}
                </p>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, flexShrink: 0, marginLeft: 16 }}>
              <button
                onClick={() => {
                  if (pendingRunId) setSelectedRunId(pendingRunId);
                  jumpToSection("enforcement");
                }}
                style={{
                  padding: "5px 14px",
                  background: "#ef4444",
                  color: "#fff",
                  border: "none",
                  borderRadius: "var(--radius-sm)",
                  fontSize: "10px",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.06em",
                  cursor: "pointer",
                  textTransform: "uppercase",
                }}
              >
                {agent.pending_action.cta_primary ?? agent.pending_action.cta ?? "Review"}
              </button>
              {agent.pending_action.cta_secondary && (
                <button
                  onClick={() => jumpToSection("contracts")}
                  style={{
                    padding: "5px 14px",
                    background: "transparent",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--radius-sm)",
                    fontSize: "10px",
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.06em",
                    cursor: "pointer",
                    textTransform: "uppercase",
                  }}
                >
                  {agent.pending_action.cta_secondary}
                </button>
              )}
            </div>
          </div>
        )}

        {/* ── Metrics ─────────────────────────────────────────────── */}
        <SectionHeader title="Performance Metrics" badge={metrics ? `${metrics.n_runs} runs` : undefined} />
        <MetricsPanel metrics={metrics} />

        {/* ── Recommendations + Anomalies ─────────────────────────── */}
        <RecommendationBanner agentId={agentId} />
        <EnhancementPanel agentId={agentId} />

        {/* ── Analytics Charts ─────────────────────────────────────── */}
        <SectionHeader title="Analytics Trends" badge="quality · trust · cost · latency" />
        <MetricsTrendCharts trends={trends} versionCheckpoints={metrics?.version_checkpoints ?? []} />

        {/* ── Contracts + Evaluation Prompt (tabbed) ──────────────── */}
        <div id="contracts">
          <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border-subtle)", marginBottom: 12 }}>
            {(["contract", "eval"] as const).map((tab) => (
              <button key={tab} onClick={() => setContractTab(tab)} style={{ all: "unset", cursor: "pointer", padding: "6px 16px", fontSize: 11, fontFamily: "var(--font-mono)", letterSpacing: "0.06em", textTransform: "uppercase", color: contractTab === tab ? "var(--text-primary)" : "var(--text-dim)", borderBottom: contractTab === tab ? "2px solid var(--amber)" : "2px solid transparent", marginBottom: -1 }}>
                {tab === "contract" ? `Contracts${contracts.length > 0 ? ` · ${contracts.length}` : ""}` : "Eval Prompt"}
              </button>
            ))}
          </div>
          {contractTab === "contract" && <ContractPanel contracts={contracts} agentId={agentId} onRefresh={handleRefresh} mode={mode} />}
          {contractTab === "eval" && <QualityRubricPanel />}
        </div>

        {/* ── Violations + Failure Attribution (tabbed) ───────────── */}
        <div id="enforcement">
          <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border-subtle)", marginBottom: 12 }}>
            {(["violations", "attribution"] as const).map((tab) => (
              <button key={tab} onClick={() => setEnfTab(tab)} style={{ all: "unset", cursor: "pointer", padding: "6px 16px", fontSize: 11, fontFamily: "var(--font-mono)", letterSpacing: "0.06em", textTransform: "uppercase", color: enfTab === tab ? "var(--text-primary)" : "var(--text-dim)", borderBottom: enfTab === tab ? "2px solid var(--amber)" : "2px solid transparent", marginBottom: -1 }}>
                {tab === "violations" ? `Enforcement${violations.length > 0 ? ` · ${violations.length}` : ""}` : `Attribution${attributions.length > 0 ? ` · ${attributions.length}` : ""}`}
              </button>
            ))}
          </div>
          {enfTab === "violations" && <ViolationPanel violations={violations} audit={audit} focusRunId={pendingRunId} onRefresh={handleRefresh} />}
          {enfTab === "attribution" && <AttributionPanel items={attributions} />}
        </div>

        {/* ── Agent Structure ────────────────────────────────────── */}
        <SectionHeader title="Agent Structure" badge="tool graph" />
        <AgentGraph
          agentId={agentId}
          subAgents={agent.type === "orchestrator" ? agent.sub_agents : undefined}
          onNavigateSubAgent={(id) => router.push(`/agents/${id}`)}
          refreshTrigger={graphRefreshKey}
        />

        {/* ── Sub-Agents (orchestrator agents) ────────────────────── */}
        {agent.type === "orchestrator" && agent.sub_agents && agent.sub_agents.length > 0 && (
          <>
            <SectionHeader title="Sub-Agents" badge={`${agent.sub_agents.length} agent${agent.sub_agents.length !== 1 ? "s" : ""}`} />
            <Panel>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10, padding: "12px 14px" }}>
                {agent.sub_agents.map((sa) => {
                  const tierStyle = TIER[(sa.current_tier as Tier) ?? "restricted"] ?? TIER.restricted;
                  const isVirtual = Boolean(sa.virtual);
                  return (
                    <div
                      key={sa.agent_id}
                      style={{
                        display: "flex", flexDirection: "column", gap: 6,
                        padding: "12px 14px",
                        background: "var(--bg-1)",
                        border: "1px solid var(--border-default)",
                        borderRadius: "var(--radius-md)",
                        textDecoration: "none",
                        transition: "border-color 0.15s, background 0.15s",
                        cursor: isVirtual ? "default" : "pointer",
                      }}
                      onMouseEnter={(e) => {
                        if (isVirtual) return;
                        (e.currentTarget as HTMLDivElement).style.borderColor = "rgba(245,158,11,0.4)";
                        (e.currentTarget as HTMLDivElement).style.background = "var(--bg-3)";
                      }}
                      onMouseLeave={(e) => {
                        if (isVirtual) return;
                        (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border-default)";
                        (e.currentTarget as HTMLDivElement).style.background = "var(--bg-1)";
                      }}
                      onClick={() => {
                        if (!isVirtual) router.push(`/agents/${sa.agent_id}`);
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-primary)", fontWeight: 600, letterSpacing: "0.02em" }}>
                          {sa.name}
                        </span>
                        <span style={{
                          fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase",
                          padding: "1px 6px", borderRadius: 3,
                          background: tierStyle.bg, color: tierStyle.text,
                          fontFamily: "var(--font-mono)",
                        }}>
                          {sa.current_tier}
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                          Trust: <span style={{ color: sa.trust_score >= 0.65 ? "var(--green)" : sa.trust_score >= 0.40 ? "var(--amber)" : "var(--red)" }}>
                            {(sa.trust_score * 100).toFixed(1)}%
                          </span>
                        </span>
                        <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                          {sa.agent_id}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--amber)", fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>
                        {isVirtual ? "workflow stage (derived from graph)" : "→ view detail"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </>
        )}

        {/* ── Parent Agent (sub-agent pages) ─────────────────────── */}
        {agent.parent_agent_id && (
          <div style={{ padding: "8px 14px", background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)" }}>
            <span style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase" }}>PARENT ORCHESTRATOR</span>
            <Link href={`/agents/${agent.parent_agent_id}`} style={{ fontSize: 11, color: "var(--amber)", textDecoration: "none" }}>
              {agent.parent_agent_id} →
            </Link>
          </div>
        )}

        {/* ── Context Flow (orchestrator agents) ──────────────────── */}
        {contextRoutes.length > 0 && (
          <>
            <SectionHeader title="Context Flow" badge="sub-agent routing" />
            <ContextFlowPanel routes={contextRoutes} />
            <TokenFlow routes={contextRoutes} />
          </>
        )}

        {/* ── Run History ─────────────────────────────────────────── */}
        {/* ── Quality Evaluation Summary ───────────────────────────── */}
        {runs.length > 0 && (() => {
          const runsWithQuality = runs.filter(r => r.quality_score !== null);
          const latestWithBreakdown = runs.find(r => r.quality_breakdown && Object.keys(r.quality_breakdown).length > 0);
          const latestWithRationale = runs.find(r => r.quality_rationale);
          if (runsWithQuality.length === 0) return null;

          const avgQuality = runsWithQuality.reduce((s, r) => s + (r.quality_score ?? 0), 0) / runsWithQuality.length;
          const checkKeys = ["output_length", "error_keywords", "format_compliance", "contract_scope"] as const;
          const checkLabels: Record<string, string> = { output_length: "Output Length", error_keywords: "No Error Keywords", format_compliance: "Format Compliance", contract_scope: "Contract Scope" };
          const avgBreakdown: Record<string, number> = {};
          if (latestWithBreakdown?.quality_breakdown) {
            checkKeys.forEach(k => {
              const vals = runs.filter(r => r.quality_breakdown && typeof r.quality_breakdown[k] === "number").map(r => r.quality_breakdown![k] as number);
              if (vals.length > 0) avgBreakdown[k] = vals.reduce((s, v) => s + v, 0) / vals.length;
            });
          }

          return (
            <>
              <button onClick={() => setQualityOpen((o) => !o)} style={{ all: "unset", cursor: "pointer", width: "100%" }}>
                <SectionHeader title="Quality Evaluation" badge={`${runsWithQuality.length} scored runs · ${qualityOpen ? "▲" : "▼"}`} />
              </button>
              {!qualityOpen ? null : <Panel>
                <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>
                  {/* Score header */}
                  <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
                    <div>
                      <div style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)", marginBottom: 4 }}>Avg Quality Score</div>
                      <div style={{ fontSize: 32, fontWeight: 700, fontFamily: "var(--font-mono)", color: avgQuality >= 0.8 ? "var(--green)" : avgQuality >= 0.6 ? "var(--amber)" : "var(--red)" }}>
                        {Math.round(avgQuality * 100)}%
                      </div>
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ height: 8, background: "var(--bg-4)", borderRadius: 4, overflow: "hidden" }}>
                        <div style={{ width: `${Math.round(avgQuality * 100)}%`, height: "100%", background: avgQuality >= 0.8 ? "var(--green)" : avgQuality >= 0.6 ? "var(--amber)" : "var(--red)", transition: "width 0.5s ease" }} />
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginTop: 4 }}>
                        across {runsWithQuality.length} evaluated run{runsWithQuality.length !== 1 ? "s" : ""}
                      </div>
                    </div>
                  </div>

                  {/* Check breakdown */}
                  {Object.keys(avgBreakdown).length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      <div style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Avg Check Scores</div>
                      {Object.entries(avgBreakdown).map(([k, v]) => {
                        const pct = Math.round(v * 100);
                        const c = pct >= 80 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)";
                        return (
                          <div key={k} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", minWidth: 170 }}>{checkLabels[k] ?? k}</span>
                            <div style={{ flex: 1, height: 5, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                              <div style={{ width: `${pct}%`, height: "100%", background: c, transition: "width 0.4s ease" }} />
                            </div>
                            <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: c, minWidth: 36, textAlign: "right" }}>{pct}%</span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Most recent LLM rationale */}
                  {latestWithRationale?.quality_rationale && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Latest LLM Rationale</span>
                        <span style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>(run #{latestWithRationale.id})</span>
                      </div>
                      <div style={{ padding: "12px 14px", background: "var(--bg-2)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.65, whiteSpace: "pre-wrap" }}>
                        {latestWithRationale.quality_rationale}
                      </div>
                    </div>
                  )}

                  {!latestWithRationale && (
                    <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)", padding: "4px 0" }}>
                      LLM rationale not available — enable <code style={{ color: "var(--amber)" }}>ENABLE_LLM_QUALITY_SCORING=true</code> and set <code style={{ color: "var(--amber)" }}>OPENAI_API_KEY</code> to activate the LLM evaluator.
                    </div>
                  )}
                </div>
              </Panel>}
            </>
          );
        })()}

        <SectionHeader title="Run History" badge={agent.type === "orchestrator" ? "click row for step trace or tree" : "click row for step trace"} />
        <Panel>
          {runs.length === 0 ? (
            <p style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--font-mono)", padding: "12px 14px" }}>No runs yet. Click RUN TASK to execute the agent.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "var(--font-mono)" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                    {["ID", "CONTRACT", "STATUS", "QUALITY", "TRUST AFTER", "LATENCY", "VIOLATIONS", "TIME"].map((h) => (
                      <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontSize: 11, color: "var(--text-dim)", letterSpacing: "0.07em", fontWeight: 500 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {runs.slice(0, 30).map((run) => (
                    <tr
                      key={run.id}
                      onClick={() => {
                        setSelectedRunId(run.id);
                        if (!run.parent_run_id && agent.type === "orchestrator") setTreeRunId(run.id);
                      }}
                      style={{
                        borderBottom: "1px solid var(--border-subtle)",
                        cursor: "pointer",
                        background: selectedRunId === run.id ? "rgba(245,158,11,0.05)" : "transparent",
                        transition: "background 0.1s",
                      }}
                      onMouseEnter={(e) => { if (selectedRunId !== run.id) (e.currentTarget as HTMLTableRowElement).style.background = "var(--bg-1)"; }}
                      onMouseLeave={(e) => { if (selectedRunId !== run.id) (e.currentTarget as HTMLTableRowElement).style.background = "transparent"; }}
                    >
                      <td style={{ padding: "7px 10px", color: "var(--text-dim)" }}>#{run.id}</td>
                      <td style={{ padding: "7px 10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", fontSize: 9 }}>
                        {run.contract_version ? `v${run.contract_version}` : "—"}
                      </td>
                      <td style={{ padding: "7px 10px" }}>
                        <span style={{ color: run.completion_status === "success" ? "var(--green)" : "var(--red)" }}>
                          {run.completion_status === "success" ? "●" : "✕"} {run.completion_status}
                        </span>
                      </td>
                      <td style={{ padding: "7px 10px", color: "var(--text-secondary)" }}>
                        {run.quality_score != null ? run.quality_score.toFixed(3) : "—"}
                      </td>
                      <td style={{ padding: "7px 10px", color: "var(--text-secondary)" }}>
                        {run.trust_score_after != null ? run.trust_score_after.toFixed(3) : "—"}
                      </td>
                      <td style={{ padding: "7px 10px", color: "var(--text-dim)" }}>
                        {run.latency_ms != null ? `${run.latency_ms}ms` : "—"}
                      </td>
                      <td style={{ padding: "7px 10px", color: run.violations && run.violations.length > 0 ? "var(--red)" : "var(--text-dim)" }}>
                        {run.violations ? run.violations.length : 0}
                      </td>
                      <td style={{ padding: "7px 10px", color: "var(--text-dim)" }}>
                        {formatLocalTimestamp(run.timestamp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {/* Run Step Drawer */}
        {selectedRunId != null && (
          <RunStepDrawer key={selectedRunId} runId={selectedRunId} onClose={() => setSelectedRunId(null)} />
        )}

        {/* Multi-agent run tree — shown for orchestrator agents when a parent run is clicked */}
        {agent.type === "orchestrator" && treeRunId != null && (
          <>
            <SectionHeader title="Orchestrator Run Tree" badge={`run #${treeRunId}`} />
            <OrchestratorRunTree key={treeRunId} runId={treeRunId} onClose={() => setTreeRunId(null)} />
          </>
        )}

        {/* Footer */}
        <footer style={{
          marginTop: 24,
          paddingTop: 16,
          borderTop: "1px solid var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <span style={{ fontSize: "10px", color: "var(--text-dim)" }}>
            norma.ai — agent governance platform — v0.1.0-alpha
          </span>
          <button
            onClick={() => router.push("/")}
            style={{
              all: "unset",
              cursor: "pointer",
              fontSize: "10px",
              color: "var(--amber)",
              letterSpacing: "0.06em",
            }}
          >
            ← BACK TO DASHBOARD
          </button>
        </footer>
      </main>
    </div>
  );
}
