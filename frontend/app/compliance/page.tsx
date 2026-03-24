"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ModeToggle } from "@/components/ModeToggle";
import { getAgents, getCompliancePosture, getViolations, type CompliancePosture } from "@/lib/api";
import type { Agent, Violation } from "@/lib/types";

export default function CompliancePage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [posture, setPosture] = useState<CompliancePosture | null>(null);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [selectedStandard, setSelectedStandard] = useState<string>("");
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAgents().then((a) => {
      setAgents(a);
      if (a.length > 0) setSelected(a[0].id);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (!selected) return;
    getCompliancePosture(selected).then(setPosture);
    getViolations(selected, 100).then(setViolations).catch(() => setViolations([]));
  }, [selected]);

  const activeStandard = selectedStandard || (posture ? Object.keys(posture.by_standard)[0] ?? "" : "");

  const selectedFinding = posture?.findings.find((f) => f.rule_id === selectedRuleId) ?? null;
  const scopedFindings = posture
    ? posture.findings.filter((f) => (activeStandard ? f.standard === activeStandard : true))
    : [];
  const matchingViolations = selectedFinding
    ? violations.filter((v) => {
        const ruleMatch = v.policy_rule.toLowerCase().includes(selectedFinding.rule_id.toLowerCase());
        const standardMatch = v.policy_rule.toLowerCase().includes(selectedFinding.standard.toLowerCase());
        return ruleMatch || standardMatch;
      })
    : [];

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-0)", color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
      <header style={{ borderBottom: "1px solid var(--border-default)", padding: "0 24px", height: 52, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/" style={{ textDecoration: "none" }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color: "var(--text-default)", letterSpacing: "0.04em" }}>
              norma.ai
            </span>
          </Link>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {[
              { label: "DASHBOARD", href: "/", active: false },
              { label: "REGISTRY", href: "/agents", active: false },
              { label: "LOG", href: "/runs", active: false },
              { label: "ALERTS", href: "/alerts", active: false },
              { label: "COMPLIANCE", href: "/compliance", active: true },
            ].map((item) => (
              <Link
                key={item.label}
                href={item.href}
                style={{
                  fontSize: "10px",
                  color: item.active ? "var(--amber)" : "var(--text-dim)",
                  cursor: "pointer",
                  letterSpacing: "0.06em",
                  textDecoration: "none",
                  fontFamily: "var(--font-mono)",
                  border: item.active ? "1px solid rgba(245,158,11,0.3)" : "1px solid var(--border-subtle)",
                  background: item.active ? "var(--amber-glow)" : "transparent",
                  borderRadius: "var(--radius-sm)",
                  padding: "3px 8px",
                }}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        <ModeToggle />
      </header>

      <main style={{ maxWidth: 1100, margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--text-dim)", letterSpacing: "0.06em" }}>AGENT</span>
          <select
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              setSelectedStandard("");
              setSelectedRuleId(null);
            }}
            style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", fontSize: 11, padding: "5px 10px" }}
          >
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.id}</option>
            ))}
          </select>
        </div>

        {loading && <div style={{ color: "var(--text-dim)", fontSize: 11 }}>Loading agents…</div>}

        {posture && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))", gap: 8 }}>
              <Metric label="Status" value={posture.passed ? "PASS" : "FAIL"} color={posture.passed ? "var(--green)" : "var(--red)"} />
              <Metric label="Rules" value={String(posture.summary.total_rules)} />
              <Metric label="Passed" value={String(posture.summary.passed_rules)} color="var(--green)" />
              <Metric label="Failed" value={String(posture.summary.failed_rules)} color={posture.summary.failed_rules > 0 ? "var(--red)" : "var(--text-primary)"} />
            </div>

            <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: 12 }}>
              <div style={{ fontSize: 12, color: "var(--text-dim)", letterSpacing: "0.06em", marginBottom: 8 }}>BY STANDARD</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 8 }}>
                {Object.entries(posture.by_standard).map(([standard, data]) => (
                  <button
                    key={standard}
                    type="button"
                    onClick={() => {
                      setSelectedStandard(standard);
                      setSelectedRuleId(null);
                    }}
                    style={{
                      border: activeStandard === standard ? "1px solid var(--amber)" : "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-sm)",
                      padding: 8,
                      textAlign: "left",
                      background: activeStandard === standard ? "var(--amber-glow)" : "var(--bg-2)",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>{standard}</div>
                    <div style={{ fontSize: 12, color: "var(--text-dim)" }}>total {data.total} · pass {data.passed} · fail {data.failed}</div>
                  </button>
                ))}
              </div>
            </div>

            <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
              <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border-subtle)", fontSize: 12, color: "var(--text-dim)", letterSpacing: "0.06em" }}>RULE FINDINGS</div>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {scopedFindings.map((f) => (
                  <button
                    type="button"
                    key={f.rule_id}
                    onClick={() => setSelectedRuleId(f.rule_id)}
                    style={{
                      border: "none",
                      borderTop: "1px solid var(--border-subtle)",
                      padding: "10px 12px",
                      display: "flex",
                      flexDirection: "column",
                      gap: 3,
                      background: selectedRuleId === f.rule_id ? "var(--bg-1)" : "transparent",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 12, color: f.passed ? "var(--green)" : "var(--red)", fontFamily: "var(--font-mono)" }}>{f.passed ? "PASS" : "FAIL"}</span>
                      <span style={{ fontSize: 11, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{f.rule_id}</span>
                      <span style={{ fontSize: 12, color: "var(--text-dim)" }}>{f.standard}</span>
                      <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-dim)", textTransform: "uppercase" }}>{f.severity}</span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-primary)" }}>{f.message}</div>
                    {f.evidence.length > 0 && (
                      <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>evidence: {f.evidence.join(", ")}</div>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {selectedFinding && (
              <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ fontSize: 12, color: "var(--text-dim)", letterSpacing: "0.06em" }}>FINDING DETAIL</div>
                <div style={{ fontSize: 12, color: selectedFinding.passed ? "var(--green)" : "var(--red)", fontFamily: "var(--font-mono)" }}>
                  {selectedFinding.rule_id} · {selectedFinding.standard} · {selectedFinding.passed ? "PASS" : "FAIL"}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-primary)" }}>{selectedFinding.message}</div>
                <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                  severity: {selectedFinding.severity}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-dim)", letterSpacing: "0.06em" }}>VIOLATING ACTIONS</div>
                {matchingViolations.length === 0 ? (
                  <div style={{ fontSize: 12, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                    No concrete violation actions mapped for this finding in recent runs.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {matchingViolations.slice(0, 6).map((v) => (
                      <div key={v.id} style={{ border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "8px 10px", background: "var(--bg-1)" }}>
                        <div style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                          run #{v.run_id ?? "—"} · {v.blocked ? "BLOCKED" : "AUDITED"}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-primary)", marginTop: 2 }}>{v.action_attempted}</div>
                        <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>{v.policy_rule}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", padding: "10px 12px" }}>
      <div style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 18, color: color ?? "var(--text-primary)", fontFamily: "var(--font-mono)", marginTop: 2 }}>{value}</div>
    </div>
  );
}
