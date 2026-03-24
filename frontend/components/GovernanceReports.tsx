import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { ComplianceReportItem, getFleetReports } from "@/lib/api";

export function GovernanceReports() {
    const [reports, setReports] = useState<ComplianceReportItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<ComplianceReportItem | null>(null);

    useEffect(() => {
        getFleetReports()
            .then((data) => {
                setReports(data);
                if (data.length > 0) setSelected(data[0]);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, []);

    if (loading) {
        return (
            <div style={{ padding: "24px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                Loading governance reports...
            </div>
        );
    }

    if (reports.length === 0) {
        return (
            <div style={{ padding: "24px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", fontSize: "11px", textAlign: "center", border: "1px dashed var(--border-default)", borderRadius: "var(--radius-md)" }}>
                No Sentinel governance reports found. Run Sentinel to generate one.
            </div>
        );
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3 style={{ margin: 0, fontSize: "13px", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    Sentinel Governance Logs
                </h3>
                <span style={{ fontSize: "10px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", padding: "2px 8px", background: "var(--bg-1)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-subtle)" }}>
                    {reports.length} report{reports.length !== 1 ? "s" : ""}
                </span>
            </div>

            {/* Fixed-height log list */}
            <div style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
                <div style={{ maxHeight: 220, overflowY: "auto" }}>
                    {reports.map((report, i) => {
                        const isSelected = selected?.id === report.id;
                        return (
                            <div
                                key={report.id}
                                onClick={() => setSelected(isSelected ? null : report)}
                                style={{
                                    display: "grid",
                                    gridTemplateColumns: "1fr auto auto",
                                    alignItems: "center",
                                    gap: 12,
                                    padding: "7px 12px",
                                    cursor: "pointer",
                                    borderTop: i > 0 ? "1px solid var(--border-subtle)" : undefined,
                                    background: isSelected ? "var(--bg-3)" : "var(--bg-2)",
                                    transition: "background 0.1s ease",
                                }}
                                onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "var(--bg-3)"; }}
                                onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "var(--bg-2)"; }}
                            >
                                <span style={{ fontSize: "11px", color: isSelected ? "var(--text-primary)" : "var(--text-secondary)", fontFamily: "var(--font-mono)", fontWeight: isSelected ? 600 : 400 }}>
                                    {new Date(report.timestamp).toLocaleString()}
                                </span>
                                <span style={{ fontSize: "9px", padding: "1px 6px", background: "rgba(99,102,241,0.1)", color: "#818cf8", borderRadius: "var(--radius-sm)", border: "1px solid rgba(99,102,241,0.2)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
                                    {report.agents_monitored} agents
                                </span>
                                <span style={{ fontSize: "9px", padding: "1px 6px", background: report.critical_issues_count > 0 ? "rgba(239,68,68,0.1)" : "rgba(34,197,94,0.1)", color: report.critical_issues_count > 0 ? "var(--red)" : "var(--green)", borderRadius: "var(--radius-sm)", border: `1px solid ${report.critical_issues_count > 0 ? "rgba(239,68,68,0.2)" : "rgba(34,197,94,0.2)"}`, fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
                                    {report.critical_issues_count} critical
                                </span>
                            </div>
                        );
                    })}
                </div>

                {/* Detail pane */}
                {selected && (
                    <div style={{ borderTop: "1px solid var(--border-default)", padding: "12px 14px", background: "var(--bg-1)", maxHeight: 260, overflowY: "auto" }}>
                        <div className="sentinel-md">
                            <ReactMarkdown>{selected.report_text}</ReactMarkdown>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
