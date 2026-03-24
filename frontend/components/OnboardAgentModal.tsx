"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  scanDirectory,
  onboardFromDirectory,
  type ScanResult,
  type AgentCandidate,
  type CreateAgentResponse,
} from "@/lib/api";

interface OnboardAgentModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (agent: CreateAgentResponse) => void;
}

type RegStatus = "pending" | "registering" | "done" | "error";

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.07em", textTransform: "uppercase" as const, fontFamily: "var(--font-mono)" }}>
      {children}
    </span>
  );
}

function Chip({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ padding: "2px 7px", background: `${color}18`, border: `1px solid ${color}30`, borderRadius: "var(--radius-sm)", fontSize: 9, color, fontFamily: "var(--font-mono)", letterSpacing: "0.04em", whiteSpace: "nowrap" as const }}>
      {label}
    </span>
  );
}

// ─── Per-candidate card (multi-select) ────────────────────────────────────────

interface AgentCandidateCardProps {
  candidate: AgentCandidate;
  selected: boolean;
  agentId: string;
  agentName: string;
  onToggle: () => void;
  onAgentIdChange: (v: string) => void;
  onAgentNameChange: (v: string) => void;
  regStatus?: RegStatus;
  regError?: string;
}

function AgentCandidateCard({
  candidate,
  selected,
  agentId,
  agentName,
  onToggle,
  onAgentIdChange,
  onAgentNameChange,
  regStatus,
  regError,
}: AgentCandidateCardProps) {
  const typeColor = candidate.type === "orchestrator"
    ? "var(--purple, #a78bfa)"
    : candidate.type === "subagent" ? "var(--blue)" : "var(--amber)";
  const confColor = candidate.confidence === "agent" ? "var(--green)" : "var(--amber)";
  const entryFile = candidate.entry_point.replace(/\\/g, "/").split("/").pop() ?? candidate.entry_point;

  const statusColor: Record<RegStatus, string> = {
    pending: "var(--text-dim)", registering: "var(--amber)", done: "var(--green)", error: "var(--red)",
  };
  const statusIcon: Record<RegStatus, string> = {
    pending: "○", registering: "◌", done: "✓", error: "✗",
  };

  return (
    <div style={{
      padding: "10px 12px",
      background: selected ? "rgba(245,158,11,0.05)" : "var(--bg-1)",
      border: `1px solid ${regStatus === "error" ? "rgba(239,68,68,0.35)" : regStatus === "done" ? "rgba(34,197,94,0.3)" : selected ? "rgba(245,158,11,0.28)" : "var(--border-default)"}`,
      borderRadius: "var(--radius-sm)",
      transition: "all 0.12s",
    }}>
      {/* Top row: checkbox + filename + chips */}
      <div
        onClick={!regStatus ? onToggle : undefined}
        style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: regStatus ? "default" : "pointer" }}
      >
        <div style={{
          marginTop: 1, flexShrink: 0, width: 14, height: 14, borderRadius: "50%",
          background: selected ? (regStatus === "done" ? "var(--green)" : "var(--amber)") : "transparent",
          border: `1.5px solid ${selected ? (regStatus === "done" ? "var(--green)" : "var(--amber)") : "var(--border-default)"}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 8, color: "var(--bg-1)",
        }}>
          {selected ? (regStatus ? statusIcon[regStatus] : "✓") : ""}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{entryFile}</span>
            <span style={{ fontSize: 8, padding: "1px 5px", background: `${typeColor}18`, border: `1px solid ${typeColor}30`, borderRadius: "var(--radius-sm)", color: typeColor, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>{candidate.type.toUpperCase()}</span>
            <span style={{ fontSize: 8, padding: "1px 5px", background: `${confColor}18`, border: `1px solid ${confColor}30`, borderRadius: "var(--radius-sm)", color: confColor, fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>{candidate.confidence === "agent" ? "HIGH CONFIDENCE" : "POSSIBLE AGENT"}</span>
            {regStatus && (
              <span style={{ fontSize: 8, padding: "1px 5px", background: `${statusColor[regStatus]}18`, border: `1px solid ${statusColor[regStatus]}30`, borderRadius: "var(--radius-sm)", color: statusColor[regStatus], fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}>{regStatus.toUpperCase()}</span>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            {candidate.tools.map((t) => <Chip key={t} label={`${t}()`} color="var(--blue)" />)}
          </div>
        </div>
      </div>

      {/* Editable ID + name — shown when selected and not yet being registered */}
      {selected && !regStatus && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 8 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <Label>Agent ID</Label>
            <input type="text" value={agentId} onChange={(e) => onAgentIdChange(e.target.value)} onClick={(e) => e.stopPropagation()}
              style={{ padding: "5px 8px", background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none" }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <Label>Display name</Label>
            <input type="text" value={agentName} onChange={(e) => onAgentNameChange(e.target.value)} onClick={(e) => e.stopPropagation()}
              style={{ padding: "5px 8px", background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none" }} />
          </div>
        </div>
      )}

      {regError && (
        <div style={{ marginTop: 6, fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{regError}</div>
      )}
    </div>
  );
}


// ─── Main modal ───────────────────────────────────────────────────────────────

export function OnboardAgentModal({ open, onClose, onCreated }: OnboardAgentModalProps) {
  const router = useRouter();
  const [step, setStep] = useState<"scan" | "register" | "done">("scan");
  const [directory, setDirectory] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);

  // Multi-select
  const [selectedCandidates, setSelectedCandidates] = useState<Set<number>>(new Set());
  const [agentIdOverrides, setAgentIdOverrides] = useState<Record<number, string>>({});
  const [agentNameOverrides, setAgentNameOverrides] = useState<Record<number, string>>({});

  // Fallback single-agent form (tools found but no structured agents)
  const [fallbackAgentId, setFallbackAgentId] = useState("");
  const [fallbackAgentName, setFallbackAgentName] = useState("");

  // Registration progress
  const [registering, setRegistering] = useState(false);
  const [registerProgress, setRegisterProgress] = useState<Map<number, RegStatus>>(new Map());
  const [registerErrors, setRegisterErrors] = useState<Map<number, string>>(new Map());
  const [createdAgents, setCreatedAgents] = useState<CreateAgentResponse[]>([]);

  const reset = useCallback(() => {
    setStep("scan"); setDirectory(""); setScanning(false); setScanError(null); setScanResult(null);
    setSelectedCandidates(new Set()); setAgentIdOverrides({}); setAgentNameOverrides({});
    setFallbackAgentId(""); setFallbackAgentName("");
    setRegistering(false); setRegisterProgress(new Map()); setRegisterErrors(new Map()); setCreatedAgents([]);
  }, []);

  const handleClose = () => { reset(); onClose(); };

  function slugify(path: string): string {
    const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
    const last = parts[parts.length - 1] ?? "agent";
    const parent = parts[parts.length - 2] ?? "agent";
    const stem = last.replace(/\.(py|js|ts)$/, "");
    const base = stem.toLowerCase() === "__init__" ? parent : `${parent}-${stem}`;
    return base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") + "-v1";
  }
  function prettify(path: string): string {
    const seg = path.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? "";
    return seg.replace(/\.(py|js|ts)$/, "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function candidateAgentId(idx: number, c: AgentCandidate) {
    return agentIdOverrides[idx] ?? slugify(c.entry_point);
  }
  function candidateAgentName(idx: number, c: AgentCandidate) {
    return agentNameOverrides[idx] ?? prettify(c.entry_point);
  }

  const handleScan = async () => {
    const dir = directory.trim();
    if (!dir) return;
    setScanning(true); setScanError(null); setScanResult(null);
    try {
      const result = await scanDirectory(dir);
      setScanResult(result);
      // Auto-select all high-confidence agents; if none, select first
      const highConf = result.agents.map((a, i) => ({ a, i })).filter(({ a }) => a.confidence === "agent").map(({ i }) => i);
      setSelectedCandidates(new Set(highConf.length > 0 ? highConf : result.agents.length > 0 ? [0] : []));
      setFallbackAgentId(slugify(dir));
      setFallbackAgentName(prettify(dir));
      setStep("register");
    } catch (e: unknown) {
      setScanError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  const handleBatchRegister = async () => {
    if (!scanResult) return;

    // Fallback path when no candidates detected
    if (scanResult.agents.length === 0) {
      if (!fallbackAgentId || !fallbackAgentName) return;
      setRegistering(true);
      try {
        const res = await onboardFromDirectory({ directory: scanResult.directory, agent_id: fallbackAgentId, name: fallbackAgentName, type: "single" });
        setCreatedAgents([res]); onCreated(res); setStep("done");
      } catch (e: unknown) {
        setScanError(e instanceof Error ? e.message : "Registration failed");
      } finally { setRegistering(false); }
      return;
    }

    const idxList = [...selectedCandidates];
    if (idxList.length === 0) return;
    setRegistering(true);
    setRegisterProgress(new Map(idxList.map(i => [i, "pending" as RegStatus])));
    setRegisterErrors(new Map());

    const created: CreateAgentResponse[] = [];
    for (const idx of idxList) {
      const c = scanResult.agents[idx];
      setRegisterProgress((prev) => new Map(prev).set(idx, "registering"));
      try {
        const res = await onboardFromDirectory({ directory: c.directory, entry_point: c.entry_point, agent_id: candidateAgentId(idx, c), name: candidateAgentName(idx, c), type: c.type });
        created.push(res); onCreated(res);
        setRegisterProgress((prev) => new Map(prev).set(idx, "done"));
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Failed";
        setRegisterErrors((prev) => new Map(prev).set(idx, msg));
        setRegisterProgress((prev) => new Map(prev).set(idx, "error"));
      }
    }
    setCreatedAgents(created); setRegistering(false); setStep("done");
  };

  const toggleAll = () => {
    if (!scanResult) return;
    setSelectedCandidates(selectedCandidates.size === scanResult.agents.length
      ? new Set()
      : new Set(scanResult.agents.map((_, i) => i)));
  };

  if (!open) return null;

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "8px 10px", background: "var(--bg-1)",
    border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)",
    color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 12,
    outline: "none", boxSizing: "border-box",
  };

  const stepIndex = ["scan", "register", "done"].indexOf(step);
  const selectedCount = selectedCandidates.size;

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.72)", backdropFilter: "blur(6px)" }}
      onClick={(e) => e.target === e.currentTarget && handleClose()}
    >
      <div
        style={{ width: 600, maxHeight: "92vh", overflowY: "auto", background: "var(--bg-2)", border: "1px solid var(--border-accent)", borderRadius: "var(--radius-lg)" }}
        className="animate-fade"
      >
        {/* Header */}
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-default)", display: "flex", justifyContent: "space-between", alignItems: "center", position: "sticky", top: 0, background: "var(--bg-2)", zIndex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
              {step === "done" ? "Onboarding Complete" : "Onboard Agents"}
            </span>
            <span style={{ fontSize: 9, padding: "1px 6px", background: "var(--amber-glow)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: "var(--radius-sm)", color: "var(--amber)", fontFamily: "var(--font-mono)" }}>
              {step === "scan" ? "STEP 1 · POINT" : step === "register" ? "STEP 2 · CONFIRM" : "DONE"}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {["scan", "register", "done"].map((st, i) => (
              <div key={st} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: i === stepIndex ? "var(--amber)" : i < stepIndex ? "var(--green)" : "var(--border-default)", transition: "background 0.2s" }} />
                {i < 2 && <div style={{ width: 14, height: 1, background: "var(--border-subtle)" }} />}
              </div>
            ))}
            <button onClick={handleClose} style={{ all: "unset", cursor: "pointer", fontSize: 14, color: "var(--text-dim)", padding: "2px 6px", marginLeft: 8 }}>✕</button>
          </div>
        </div>

        {/* ── STEP 1: SCAN ─────────────────────────────────────────── */}
        {step === "scan" && (
          <div style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 16 }}>
            <p style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.65, margin: 0 }}>
              Point norma at a Python directory. It will scan for{" "}
              <span style={{ color: "var(--amber)" }}>@tool</span> functions, detect agent patterns, generate contracts for every agent found — then register them all in one batch.
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <Label>Agent directory path</Label>
              <div style={{ display: "flex", gap: 8 }}>
                <input type="text" value={directory} onChange={(e) => setDirectory(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !scanning && handleScan()}
                  placeholder="/absolute/path/to/your/agents/" style={{ ...inputStyle, flex: 1 }} autoFocus />
                <button onClick={handleScan} disabled={scanning || !directory.trim()}
                  style={{ padding: "8px 14px", background: scanning ? "var(--bg-3)" : "var(--amber-glow)", border: `1px solid rgba(245,158,11,${scanning ? "0.1" : "0.35"})`, borderRadius: "var(--radius-sm)", color: scanning ? "var(--text-dim)" : "var(--amber)", fontSize: 11, fontFamily: "var(--font-mono)", cursor: scanning || !directory.trim() ? "not-allowed" : "pointer", letterSpacing: "0.06em", fontWeight: 600, whiteSpace: "nowrap" as const, flexShrink: 0 }}>
                  {scanning ? "SCANNING…" : "SCAN →"}
                </button>
              </div>
            </div>

            {scanError && (
              <div style={{ padding: "8px 10px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-sm)", fontSize: 11, color: "var(--red)", fontFamily: "var(--font-mono)" }}>{scanError}</div>
            )}

            <div style={{ padding: "10px 12px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)" }}>
              <Label>What norma does on scan</Label>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 5 }}>
                {[
                  "AST-parses Python files for @tool functions — never executes your code",
                  "Detects LangChain / LangGraph patterns: agents, orchestrators, sub-agents",
                  "Groups files into agent candidates with confidence scoring",
                  "Extracts data path hints and auto-generates allow/deny contract preview",
                  "Registers all selected agents in one batch with a single click",
                ].map((text, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                    <span style={{ color: "var(--amber)", flexShrink: 0 }}>↳</span>
                    <span>{text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── STEP 2: CONFIRM ──────────────────────────────────────── */}
        {step === "register" && scanResult && (
          <div style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 14 }}>

            {/* Scan summary */}
            <div style={{ padding: "10px 14px", background: "rgba(34,197,94,0.05)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: "var(--radius-sm)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "var(--green)", fontFamily: "var(--font-mono)" }}>● SCAN COMPLETE</span>
              <div style={{ display: "flex", gap: 10, fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                <span>{scanResult.files_scanned} file{scanResult.files_scanned !== 1 ? "s" : ""}</span>
                <span style={{ color: "var(--amber)" }}>{scanResult.tool_names.length} tools</span>
                {scanResult.agents.length > 0 && <span style={{ color: "var(--blue)" }}>{scanResult.agents.length} agent{scanResult.agents.length !== 1 ? "s" : ""} detected</span>}
                {scanResult.file_hash && <span>#{scanResult.file_hash}</span>}
              </div>
            </div>

            {/* Multi-select agent candidates */}
            {scanResult.agents.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <Label>
                    {scanResult.agents.length === 1
                      ? "Agent detected"
                      : `Select agents to register (${selectedCount} of ${scanResult.agents.length} selected)`}
                  </Label>
                  {scanResult.agents.length > 1 && (
                    <button onClick={toggleAll} style={{ all: "unset", cursor: "pointer", fontSize: 9, color: "var(--amber)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em" }}>
                      {selectedCount === scanResult.agents.length ? "DESELECT ALL" : "SELECT ALL"}
                    </button>
                  )}
                </div>
                {scanResult.agents.map((candidate, idx) => (
                  <AgentCandidateCard
                    key={candidate.entry_point}
                    candidate={candidate}
                    selected={selectedCandidates.has(idx)}
                    agentId={candidateAgentId(idx, candidate)}
                    agentName={candidateAgentName(idx, candidate)}
                    onToggle={() => setSelectedCandidates((prev) => { const next = new Set(prev); if (next.has(idx)) next.delete(idx); else next.add(idx); return next; })}
                    onAgentIdChange={(v) => setAgentIdOverrides((prev) => ({ ...prev, [idx]: v }))}
                    onAgentNameChange={(v) => setAgentNameOverrides((prev) => ({ ...prev, [idx]: v }))}
                    regStatus={registerProgress.get(idx)}
                    regError={registerErrors.get(idx)}
                  />
                ))}
              </div>
            )}

            {/* Fallback: no structured agents detected */}
            {scanResult.agents.length === 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {scanResult.tools.length > 0 && (
                  <div style={{ padding: "10px 12px", background: "var(--bg-1)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)" }}>
                    <Label>Tools found</Label>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                      {scanResult.tools.map((t) => <Chip key={t.name} label={`${t.name}()`} color="var(--blue)" />)}
                    </div>
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <Label>Agent ID *</Label>
                    <input type="text" value={fallbackAgentId} onChange={(e) => setFallbackAgentId(e.target.value)} style={inputStyle} placeholder="my-agent-v1" autoFocus />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <Label>Display name *</Label>
                    <input type="text" value={fallbackAgentName} onChange={(e) => setFallbackAgentName(e.target.value)} style={inputStyle} placeholder="My Agent" />
                  </div>
                </div>
              </div>
            )}

            {/* Action bar */}
            <div style={{ display: "flex", gap: 8, justifyContent: "space-between", alignItems: "center", paddingTop: 4 }}>
              <button onClick={() => { setStep("scan"); setScanResult(null); setSelectedCandidates(new Set()); }}
                style={{ padding: "6px 14px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: 10, fontFamily: "var(--font-mono)", cursor: "pointer", letterSpacing: "0.04em" }}>
                ← RESCAN
              </button>
              <button onClick={handleBatchRegister}
                disabled={registering || (scanResult.agents.length > 0 ? selectedCount === 0 : !fallbackAgentId || !fallbackAgentName)}
                style={{ padding: "6px 18px", background: registering ? "var(--bg-3)" : "var(--amber-glow)", border: `1px solid rgba(245,158,11,${registering ? "0.1" : "0.35"})`, borderRadius: "var(--radius-sm)", color: registering ? "var(--text-dim)" : "var(--amber)", fontSize: 10, fontFamily: "var(--font-mono)", cursor: registering ? "not-allowed" : "pointer", letterSpacing: "0.06em", fontWeight: 700, whiteSpace: "nowrap" as const }}>
                {registering
                  ? `REGISTERING (${[...registerProgress.values()].filter(s => s === "done").length}/${selectedCount})…`
                  : scanResult.agents.length > 0
                    ? `REGISTER ${selectedCount > 1 ? `ALL ${selectedCount} ` : ""}→`
                    : "REGISTER & MONITOR →"}
              </button>
            </div>
          </div>
        )}

        {/* ── STEP 3: DONE ─────────────────────────────────────────── */}
        {step === "done" && (
          <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 40, height: 40, borderRadius: "50%", background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: "var(--green)", flexShrink: 0 }}>
                {registerErrors.size === 0 ? "✓" : "⚠"}
              </div>
              <div>
                <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-mono)", margin: 0 }}>
                  {createdAgents.length} agent{createdAgents.length !== 1 ? "s" : ""} onboarded
                  {registerErrors.size > 0 && <span style={{ color: "var(--amber)", fontWeight: 400, fontSize: 10, marginLeft: 8 }}>({registerErrors.size} failed)</span>}
                </p>
                <p style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", margin: "2px 0 0" }}>
                  Contract generated · enforcement ready · sample run complete
                </p>
              </div>
            </div>

            {/* Per-agent results */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {createdAgents.map((agent) => (
                <div key={agent.id} style={{ padding: "10px 12px", background: "var(--bg-1)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: "var(--radius-sm)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <div>
                    <span style={{ fontSize: 11, color: "var(--green)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>✓ </span>
                    <span style={{ fontSize: 11, color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600 }}>{agent.name ?? agent.id}</span>
                    <span style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginLeft: 8 }}>{agent.id}</span>
                  </div>
                  <button onClick={() => { handleClose(); router.push(`/agents/${agent.id}`); }}
                    style={{ all: "unset", cursor: "pointer", fontSize: 9, color: "var(--amber)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", whiteSpace: "nowrap" }}>
                    VIEW →
                  </button>
                </div>
              ))}
              {[...registerErrors.entries()].map(([idx, err]) => {
                const c = scanResult?.agents[idx];
                return (
                  <div key={idx} style={{ padding: "8px 10px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "var(--radius-sm)", fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
                    ✗ {c?.entry_point.split("/").pop()}: {err}
                  </div>
                );
              })}
            </div>

            <p style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", lineHeight: 1.65, margin: 0 }}>
              Review and activate each contract in the agent view. Enforcement starts as soon as a contract is approved.
            </p>

            <div style={{ display: "flex", gap: 8 }}>
              {createdAgents.length === 1 && (
                <button onClick={() => { handleClose(); router.push(`/agents/${createdAgents[0].id}`); }}
                  style={{ padding: "7px 18px", background: "var(--amber-glow)", border: "1px solid rgba(245,158,11,0.35)", borderRadius: "var(--radius-sm)", color: "var(--amber)", fontSize: 10, fontFamily: "var(--font-mono)", cursor: "pointer", letterSpacing: "0.06em", fontWeight: 700 }}>
                  VIEW AGENT →
                </button>
              )}
              <button onClick={handleClose}
                style={{ padding: "7px 14px", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: 10, fontFamily: "var(--font-mono)", cursor: "pointer", letterSpacing: "0.04em" }}>
                DONE
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
