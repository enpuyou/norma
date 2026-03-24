"use client";

import { useMemo, useState } from "react";
import { Brush, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AgentMetricTrends, VersionCheckpoint } from "@/lib/api";

interface Props {
  trends: AgentMetricTrends | null;
  /** Contract version change events to draw as vertical markers on charts */
  versionCheckpoints?: VersionCheckpoint[];
}

const PALETTE = {
  quality: "#22c55e",
  trust: "#f59e0b",
  cost: "#60a5fa",
  latency: "#a78bfa",
  checkpoint: "#e879f9",    // contract change
  modelChange: "#fb923c",   // model change
  codeChange: "#38bdf8",    // code version change
};

function formatTimestampLabel(value: number, granularity: string) {
  const date = new Date(value);
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return granularity === "day" ? `${mm}-${dd}` : `${mm}-${dd} ${hh}:${min}`;
}

export function MetricsTrendCharts({ trends, versionCheckpoints = [] }: Props) {
  const [showCheckpoints, setShowCheckpoints] = useState(false);
  const points = useMemo(() => trends?.points ?? [], [trends]);
  const granularity = trends?.granularity ?? "day";
  const [zoomRange, setZoomRange] = useState<{ startIndex: number; endIndex: number } | null>(null);

  const chartData = useMemo(() => {
    return points.map((p) => ({
      ts: new Date(p.bucket_start ?? p.date).getTime(),
      date: p.bucket_label ?? p.date.slice(5),
      qualityPct: p.avg_quality != null ? Math.round(p.avg_quality * 1000) / 10 : null,
      cost: Number(p.total_cost_usd.toFixed(4)),
      trustPct: p.trust_score_end != null ? Math.round(p.trust_score_end * 1000) / 10 : null,
      avgLatencyMs: p.avg_latency_ms != null ? Math.round(p.avg_latency_ms) : null,
      runCount: p.run_count,
    }));
  }, [points]);

  const fullZoomRange = chartData.length
    ? { startIndex: 0, endIndex: Math.max(0, chartData.length - 1) }
    : null;

  const effectiveZoomRange = zoomRange && fullZoomRange
    ? {
        startIndex: Math.max(0, Math.min(zoomRange.startIndex, fullZoomRange.endIndex)),
        endIndex: Math.max(0, Math.min(zoomRange.endIndex, fullZoomRange.endIndex)),
      }
    : fullZoomRange;

  const normalizedZoomRange = effectiveZoomRange
    ? {
        startIndex: Math.min(effectiveZoomRange.startIndex, effectiveZoomRange.endIndex),
        endIndex: Math.max(effectiveZoomRange.startIndex, effectiveZoomRange.endIndex),
      }
    : null;

  const visibleDomain = normalizedZoomRange && chartData.length
    ? [
        chartData[normalizedZoomRange.startIndex]?.ts ?? chartData[0]?.ts ?? 0,
        chartData[normalizedZoomRange.endIndex]?.ts ?? chartData[chartData.length - 1]?.ts ?? 0,
      ]
    : ["dataMin", "dataMax"] as const;

  const canZoom = chartData.length > 1;

  const isZoomed = !!normalizedZoomRange
    && (
      normalizedZoomRange.startIndex > 0
      || normalizedZoomRange.endIndex < chartData.length - 1
    );

  const updateZoomRange = (nextStart: number, nextEnd: number) => {
    if (!fullZoomRange) return;
    const startIndex = Math.max(0, Math.min(nextStart, fullZoomRange.endIndex));
    const endIndex = Math.max(startIndex, Math.min(nextEnd, fullZoomRange.endIndex));
    setZoomRange({ startIndex, endIndex });
  };

  const zoomByFactor = (factor: number) => {
    if (!normalizedZoomRange || !fullZoomRange) return;
    const currentSize = normalizedZoomRange.endIndex - normalizedZoomRange.startIndex + 1;
    const minSize = Math.min(6, chartData.length);
    const maxSize = chartData.length;
    const nextSize = Math.max(minSize, Math.min(maxSize, Math.round(currentSize * factor)));
    const center = (normalizedZoomRange.startIndex + normalizedZoomRange.endIndex) / 2;
    let startIndex = Math.round(center - (nextSize - 1) / 2);
    let endIndex = startIndex + nextSize - 1;
    if (startIndex < 0) {
      endIndex += -startIndex;
      startIndex = 0;
    }
    if (endIndex > fullZoomRange.endIndex) {
      startIndex -= endIndex - fullZoomRange.endIndex;
      endIndex = fullZoomRange.endIndex;
    }
    updateZoomRange(startIndex, endIndex);
  };

  const panBy = (delta: number) => {
    if (!normalizedZoomRange || !fullZoomRange) return;
    const windowSize = normalizedZoomRange.endIndex - normalizedZoomRange.startIndex;
    let startIndex = normalizedZoomRange.startIndex + delta;
    let endIndex = normalizedZoomRange.endIndex + delta;
    if (startIndex < 0) {
      endIndex += -startIndex;
      startIndex = 0;
    }
    if (endIndex > fullZoomRange.endIndex) {
      startIndex -= endIndex - fullZoomRange.endIndex;
      endIndex = fullZoomRange.endIndex;
    }
    if (endIndex - startIndex !== windowSize) {
      startIndex = Math.max(0, endIndex - windowSize);
    }
    updateZoomRange(startIndex, endIndex);
  };

  const handleChartWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!canZoom) return;
    event.preventDefault();
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      const panStep = Math.max(1, Math.round((normalizedZoomRange?.endIndex ?? chartData.length - 1 - (normalizedZoomRange?.startIndex ?? 0)) / 8));
      panBy(event.deltaX > 0 ? panStep : -panStep);
      return;
    }
    zoomByFactor(event.deltaY > 0 ? 1.2 : 0.8);
  };

  // Map checkpoint timestamps to x-axis date labels so recharts can position them.
  // With "run" granularity, bucket_start is the exact run ISO timestamp — compare directly
  // rather than trying to re-parse the display label string.
  const checkpointLabels = useMemo(() => {
    if (!showCheckpoints || !versionCheckpoints.length || !chartData.length) return [];
    return versionCheckpoints.map((vc) => {
      const vcTime = new Date(vc.timestamp).getTime();
      return {
        x: vcTime,
        version: vc.contract_version,
        approvedBy: vc.approved_by,
        changeType: vc.change_type ?? "contract",
        displayLabel: vc.display_label ?? `v${vc.contract_version}`,
        displayTime: formatTimestampLabel(vcTime, granularity),
      };
    });
  }, [versionCheckpoints, chartData, showCheckpoints, granularity]);

  if (!points.length) {
    return (
      <div style={{ padding: "12px 14px", border: "1px dashed var(--border-subtle)", borderRadius: "var(--radius-sm)", color: "var(--text-dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
        No trend points yet.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.05em", textTransform: "uppercase" }}>
          Trend granularity: {granularity}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {canZoom && (
            <span style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              scroll to zoom · shift/trackpad sideways to pan
            </span>
          )}
          {canZoom && (
            <>
              <button
                onClick={() => zoomByFactor(0.8)}
                title="Zoom in"
                style={{
                  all: "unset",
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                  color: "var(--text-default)",
                  padding: "2px 7px",
                  border: "1px solid var(--border-default)",
                  borderRadius: 3,
                }}
              >
                +
              </button>
              <button
                onClick={() => zoomByFactor(1.25)}
                title="Zoom out"
                style={{
                  all: "unset",
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                  color: "var(--text-default)",
                  padding: "2px 7px",
                  border: "1px solid var(--border-default)",
                  borderRadius: 3,
                }}
              >
                −
              </button>
            </>
          )}
          {isZoomed && (
            <button
              onClick={() => setZoomRange(null)}
              title="Reset trend zoom"
              style={{
                all: "unset",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 4,
                fontSize: 9,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                fontFamily: "var(--font-mono)",
                color: "var(--text-dim)",
                padding: "2px 6px",
                border: "1px solid var(--border-subtle)",
                borderRadius: 3,
              }}
            >
              Reset zoom
            </button>
          )}
          {versionCheckpoints.length > 0 && (
            <button
              onClick={() => setShowCheckpoints((v) => !v)}
              title={showCheckpoints ? "Hide version markers" : "Show version markers"}
              style={{
                all: "unset",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 4,
                fontSize: 9,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                fontFamily: "var(--font-mono)",
                color: showCheckpoints ? PALETTE.checkpoint : "var(--text-dim)",
                padding: "2px 6px",
                border: `1px solid ${showCheckpoints ? "rgba(232, 121, 249, 0.3)" : "var(--border-subtle)"}`,
                borderRadius: 3,
                transition: "color 0.15s, border-color 0.15s",
              }}
            >
              <span style={{ fontSize: 10 }}>🏷</span>
              Changes ({versionCheckpoints.length})
            </button>
          )}
          <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            {chartData.length} points
          </div>
        </div>
      </div>

      {canZoom && normalizedZoomRange && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "4px 8px",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-sm)",
          background: "rgba(148, 163, 184, 0.04)",
        }}>
          <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Zoom window
          </div>
          <div style={{ fontSize: 10, color: "var(--text-default)", fontFamily: "var(--font-mono)" }}>
            {formatTimestampLabel(visibleDomain[0] as number, granularity)} → {formatTimestampLabel(visibleDomain[1] as number, granularity)}
          </div>
        </div>
      )}

      {/* Version checkpoint legend */}
      {showCheckpoints && checkpointLabels.length > 0 && (
        <div style={{
          display: "flex",
          flexWrap: "nowrap",
          gap: 6,
          padding: "6px 10px",
          background: "rgba(232, 121, 249, 0.04)",
          border: "1px solid rgba(232, 121, 249, 0.15)",
          borderRadius: "var(--radius-sm)",
          overflowX: "auto",
          scrollbarWidth: "thin",
          scrollbarColor: "rgba(148,163,184,0.2) transparent",
        }}>
          {checkpointLabels.map((cp, idx) => {
            const color = cp.changeType === "model" ? PALETTE.modelChange : cp.changeType === "code" ? PALETTE.codeChange : PALETTE.checkpoint;
            const bg = cp.changeType === "model" ? "rgba(251,146,60,0.08)" : cp.changeType === "code" ? "rgba(56,189,248,0.08)" : "rgba(232,121,249,0.08)";
            const border = cp.changeType === "model" ? "1px solid rgba(251,146,60,0.2)" : cp.changeType === "code" ? "1px solid rgba(56,189,248,0.2)" : "1px solid rgba(232,121,249,0.2)";
            const icon = cp.changeType === "model" ? "⚙" : cp.changeType === "code" ? "⬡" : "📋";
            return (
              <span key={idx} style={{ fontSize: 9, fontFamily: "var(--font-mono)", color, padding: "1px 6px", background: bg, border, borderRadius: 3, flexShrink: 0, whiteSpace: "nowrap" }}>
                {icon} {cp.displayLabel} @ {cp.displayTime}
                {cp.approvedBy && <span style={{ color: "var(--text-dim)", marginLeft: 3 }}>by {cp.approvedBy}</span>}
              </span>
            );
          })}
        </div>
      )}

      {/* Quality · Trust · Cost chart */}
      <div onWheelCapture={handleChartWheel} style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "8px 10px" }}>
        <div style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", marginBottom: 6 }}>QUALITY · TRUST · COST</div>
        <div style={{ height: 256 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart syncId="agent-trends" data={chartData} margin={{ top: 8, right: 14, left: 0, bottom: 4 }}>
              <XAxis type="number" dataKey="ts" domain={visibleDomain} tickFormatter={(value) => formatTimestampLabel(Number(value), granularity)} minTickGap={28} tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis yAxisId="pct" tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false} domain={[0, 100]} />
              <YAxis yAxisId="cost" orientation="right" tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip labelFormatter={(value) => formatTimestampLabel(Number(value), granularity)} contentStyle={{ background: "#111827", border: "1px solid #334155", borderRadius: 6, color: "#e2e8f0" }} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }} />
              {/* Version checkpoint markers */}
              {showCheckpoints && checkpointLabels.map((cp, idx) => {
                const color = cp.changeType === "model" ? PALETTE.modelChange : cp.changeType === "code" ? PALETTE.codeChange : PALETTE.checkpoint;
                return (
                  <ReferenceLine
                    key={`cp-qtc-${idx}`}
                    yAxisId="pct"
                    x={cp.x}
                    stroke={color}
                    strokeDasharray="3 3"
                    strokeWidth={1.5}
                    opacity={0.7}
                    label={{
                      value: cp.displayLabel,
                      position: "insideTopLeft",
                      offset: idx % 2 === 0 ? 4 : 18,
                      fill: color,
                      fontSize: 9,
                      fontFamily: "monospace",
                    }}
                  />
                );
              })}
              <Line yAxisId="pct" type="monotone" dataKey="qualityPct" name="Quality %" stroke={PALETTE.quality} strokeWidth={2} dot={false} connectNulls />
              <Line yAxisId="pct" type="monotone" dataKey="trustPct" name="Trust %" stroke={PALETTE.trust} strokeWidth={2} dot={false} connectNulls />
              <Line yAxisId="cost" type="monotone" dataKey="cost" name="Cost $" stroke={PALETTE.cost} strokeWidth={2} dot={false} connectNulls />
              {canZoom && normalizedZoomRange && (
                <Brush
                  dataKey="ts"
                  height={24}
                  stroke="rgba(96, 165, 250, 0.7)"
                  fill="rgba(15, 23, 42, 0.9)"
                  travellerWidth={10}
                  startIndex={normalizedZoomRange.startIndex}
                  endIndex={normalizedZoomRange.endIndex}
                  tickFormatter={(value) => formatTimestampLabel(Number(value), granularity)}
                  onChange={(range) => {
                    if (
                      typeof range?.startIndex === "number"
                      && typeof range?.endIndex === "number"
                    ) {
                      updateZoomRange(range.startIndex, range.endIndex);
                    }
                  }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Latency chart */}
      <div onWheelCapture={handleChartWheel} style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "8px 10px" }}>
        <div style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", marginBottom: 6 }}>LATENCY</div>
        <div style={{ height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart syncId="agent-trends" data={chartData} margin={{ top: 8, right: 14, left: 0, bottom: 4 }}>
              <XAxis type="number" dataKey="ts" domain={visibleDomain} tickFormatter={(value) => formatTimestampLabel(Number(value), granularity)} minTickGap={28} tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip labelFormatter={(value) => formatTimestampLabel(Number(value), granularity)} contentStyle={{ background: "#111827", border: "1px solid #334155", borderRadius: 6, color: "#e2e8f0" }} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }} />
              {showCheckpoints && checkpointLabels.map((cp, idx) => (
                <ReferenceLine
                  key={`cp-lat-${idx}`}
                  x={cp.x}
                  stroke={cp.changeType === "model" ? PALETTE.modelChange : cp.changeType === "code" ? PALETTE.codeChange : PALETTE.checkpoint}
                  strokeDasharray="3 3"
                  strokeWidth={1.5}
                  opacity={0.7}
                />
              ))}
              <Line type="monotone" dataKey="avgLatencyMs" name="Avg Latency (ms)" stroke={PALETTE.latency} strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
