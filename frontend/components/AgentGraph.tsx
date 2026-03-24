"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import ELK from "elkjs/lib/elk.bundled.js";
import { getAgentGraph, type AgentGraphData } from "@/lib/api";

interface AgentGraphProps {
  agentId: string;
  activeToolName?: string | null;
  subAgents?: { agent_id: string; name: string; trust_score: number; current_tier: string; virtual?: boolean }[];
  onNavigateSubAgent?: (agentId: string) => void;
  refreshTrigger?: number;
}

type LayoutMode = "pipeline" | "explore";

interface D3Node extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: "agent" | "tool" | "data" | "subagent" | "model";
  status?: "allowed" | "denied";
  description?: string;
  phaseId?: string;
  phaseName?: string;
  trustScore?: number;
  tier?: string;
  virtual?: boolean;
}

interface D3Link extends d3.SimulationLinkDatum<D3Node> {
  edgeType: "uses" | "blocked" | "reads" | "delegates" | "sequence";
  sourceId: string;
  targetId: string;
  order?: number;
  phaseId?: string;
  telemetry?: {
    run_id?: number;
    span_id?: string;
    parent_span_id?: string | null;
    span_type?: string;
    name?: string;
    status?: string;
    model_name?: string | null;
    tokens_in?: number | null;
    tokens_out?: number | null;
    cost_usd?: number | null;
    latency_ms?: number | null;
    start_time?: string | null;
    end_time?: string | null;
    input_preview?: string | null;
    output_preview?: string | null;
    attributes?: Record<string, unknown>;
    run_input_tokens?: number | null;
    run_output_tokens?: number | null;
    run_cost_usd?: number | null;
    run_latency_ms?: number | null;
    run_quality_score?: number | null;
    timestamp?: string | null;
  };
}

interface DetailInfo {
  type: "node" | "edge";
  node?: D3Node;
  edge?: D3Link;
  sourceNode?: D3Node;
  targetNode?: D3Node;
}

const W = 900;
const H = 500;
const MINIMAP_W = 170;
const MINIMAP_H = 110;

// Node sizes: agent is largest (hub), tools and subagents mid-sized, data/model smaller.
// Ratio goal: agent ~1.5× tool, tool ~1.25× data. These feed into radius and ELK layout.
const NODE_SIZES: Record<string, number> = { agent: 44, tool: 32, data: 26, subagent: 36, model: 32 };
const NODE_COLORS: Record<string, { fill: string; stroke: string; text: string }> = {
  agent:        { fill: "rgba(245,158,11,0.15)", stroke: "rgba(245,158,11,0.75)", text: "#f5f5f5" },
  tool_allowed: { fill: "rgba(34,197,94,0.12)",  stroke: "rgba(34,197,94,0.70)",  text: "rgba(34,197,94,0.95)" },
  tool_denied:  { fill: "rgba(239,68,68,0.12)",  stroke: "rgba(239,68,68,0.70)",  text: "rgba(239,68,68,0.95)" },
  data:         { fill: "rgba(99,162,241,0.10)",  stroke: "rgba(99,162,241,0.60)", text: "rgba(99,162,241,0.95)" },
  data_denied:  { fill: "rgba(239,68,68,0.10)",  stroke: "rgba(239,68,68,0.60)",  text: "rgba(239,68,68,0.90)" },
  subagent:     { fill: "rgba(168,85,247,0.14)",  stroke: "rgba(168,85,247,0.72)", text: "rgba(168,85,247,0.95)" },
  model:        { fill: "rgba(99,102,241,0.14)",  stroke: "rgba(99,102,241,0.65)", text: "rgba(165,180,252,1.00)" },
};

const PHASE_PALETTE = [
  "#22c55e",
  "#3b82f6",
  "#f59e0b",
  "#a855f7",
  "#14b8a6",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#84cc16",
  "#f43f5e",
  "#f97316",
  "#10b981",
];

function getNodeColor(node: D3Node) {
  if (node.type === "agent") return NODE_COLORS.agent;
  if (node.type === "subagent") return NODE_COLORS.subagent;
  if (node.type === "model") return NODE_COLORS.model;
  if (node.type === "data") return node.status === "denied" ? NODE_COLORS.data_denied : NODE_COLORS.data;
  return node.status === "denied" ? NODE_COLORS.tool_denied : NODE_COLORS.tool_allowed;
}

function baseEdgeColor(type: D3Link["edgeType"]) {
  switch (type) {
    case "sequence":  return "rgba(245,158,11,0.70)";
    case "blocked":   return "rgba(239,68,68,0.55)";
    case "reads":     return "rgba(99,162,241,0.45)";
    case "delegates": return "rgba(168,85,247,0.55)";
    default:          return "rgba(245,158,11,0.40)";
  }
}

function buildPhaseColorMap(ids: string[]): Map<string, string> {
  const unique = Array.from(new Set(ids.filter(Boolean)));
  const map = new Map<string, string>();
  unique.forEach((id, idx) => {
    if (idx < PHASE_PALETTE.length) {
      map.set(id, PHASE_PALETTE[idx]);
    } else {
      const hue = (idx * 47) % 360;
      map.set(id, `hsl(${hue} 72% 56%)`);
    }
  });
  return map;
}

function phaseColor(phaseId?: string, map?: Map<string, string>): string {
  if (!phaseId) return "rgba(148,163,184,0.55)";
  if (map?.has(phaseId)) return map.get(phaseId)!;
  return "rgba(148,163,184,0.55)";
}

function nodeRadius(node: D3Node): number {
  if (node.type === "model") return 46;
  if (node.type === "data") return 36;
  return (NODE_SIZES[node.type] || 18) + 4;
}

function edgePath(d: D3Link, nodes: D3Node[]): string {
  const s = nodes.find((n) => n.id === d.sourceId);
  const t = nodes.find((n) => n.id === d.targetId);
  if (!s || !t) return "";

  const sx = s.x ?? 0;
  const sy = s.y ?? 0;
  const tx = t.x ?? 0;
  const ty = t.y ?? 0;

  const dx = tx - sx;
  const dy = ty - sy;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;

  const startPad = nodeRadius(s) + 3;
  const endPad = nodeRadius(t) + 3;
  const x1 = sx + ux * startPad;
  const y1 = sy + uy * startPad;
  const x2 = tx - ux * endPad;
  const y2 = ty - uy * endPad;

  const bendNormalX = -uy;
  const bendNormalY = ux;
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;

  let amp = Math.max(12, Math.min(36, dist * 0.13));
  if (d.edgeType === "sequence") amp = Math.max(10, Math.min(22, dist * 0.1));
  if (d.edgeType === "delegates") amp = Math.max(16, Math.min(42, dist * 0.16));

  const dirSeed = `${d.sourceId}|${d.targetId}|${d.phaseId ?? ""}`;
  const dir = dirSeed.length % 2 === 0 ? 1 : -1;
  const cx = midX + bendNormalX * amp * dir;
  const cy = midY + bendNormalY * amp * dir;

  return `M ${x1} ${y1} Q ${cx} ${cy}, ${x2} ${y2}`;
}

function DetailPanel({ detail, onClose }: { detail: DetailInfo; onClose: () => void }) {
  if (detail.type === "node" && detail.node) {
    const n = detail.node;
    const colors = getNodeColor(n);
    return (
      <div style={{ position: "absolute", top: 8, right: 8, width: 280, zIndex: 20, background: "var(--bg-2)", border: `1px solid ${colors.stroke}`, borderRadius: "var(--radius-md)", padding: "10px 12px", fontFamily: "var(--font-mono)", fontSize: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <span style={{ color: colors.text, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>{n.type}</span>
          <button onClick={onClose} style={{ all: "unset", cursor: "pointer", color: "var(--text-dim)", fontSize: 9 }}>✕</button>
        </div>
        <div style={{ color: "var(--text-primary)", fontSize: 12, fontWeight: 500, marginBottom: 6 }}>{n.label}</div>
        <div style={{ color: "var(--text-dim)", fontSize: 9, marginBottom: 4 }}>id: {n.id}</div>
        {n.status && <div style={{ color: n.status === "denied" ? "var(--red)" : "var(--green)", fontSize: 9, marginBottom: 4 }}>status: {n.status}</div>}
        {n.phaseName && <div style={{ color: "var(--text-dim)", fontSize: 9, marginBottom: 4 }}>phase: {n.phaseName}</div>}
        {n.type === "subagent" && n.tier && <div style={{ color: "var(--text-dim)", fontSize: 9, marginBottom: 4 }}>tier: {n.tier}</div>}
        {n.type === "subagent" && typeof n.trustScore === "number" && <div style={{ color: "var(--text-dim)", fontSize: 9, marginBottom: 4 }}>trust: {(n.trustScore * 100).toFixed(1)}%</div>}
        {n.description && <div style={{ color: "var(--text-dim)", fontSize: 9, lineHeight: 1.4 }}>{n.description}</div>}
      </div>
    );
  }

  if (detail.type === "edge" && detail.edge) {
    const e = detail.edge;
    return (
      <div style={{ position: "absolute", top: 8, right: 8, width: 320, zIndex: 20, background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", padding: "10px 12px", fontFamily: "var(--font-mono)", fontSize: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <span style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>{e.edgeType}</span>
          <button onClick={onClose} style={{ all: "unset", cursor: "pointer", color: "var(--text-dim)", fontSize: 9 }}>✕</button>
        </div>
        <div style={{ color: "var(--text-secondary)", lineHeight: 1.5 }}>
          <span style={{ color: "var(--text-dim)" }}>from:</span> {detail.sourceNode?.label ?? e.sourceId}<br />
          <span style={{ color: "var(--text-dim)" }}>to:</span> {detail.targetNode?.label ?? e.targetId}
        </div>
        {typeof e.order === "number" && <div style={{ marginTop: 6, color: "var(--amber)", fontSize: 9 }}>STEP {e.order}</div>}
        {e.phaseId && <div style={{ marginTop: 4, color: "var(--text-dim)", fontSize: 9 }}>phase: {e.phaseId}</div>}
        {e.telemetry && (
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", color: "var(--text-dim)", fontSize: 9 }}>
              {e.telemetry.model_name && <span>model:{e.telemetry.model_name}</span>}
              {e.telemetry.status && <span>status:{e.telemetry.status}</span>}
              {e.telemetry.parent_span_id && <span>parent:{e.telemetry.parent_span_id}</span>}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", color: "var(--text-dim)", fontSize: 9 }}>
              {e.telemetry.span_type && <span>{e.telemetry.span_type}</span>}
              {typeof e.telemetry.tokens_in === "number" && <span>in:{e.telemetry.tokens_in}</span>}
              {typeof e.telemetry.tokens_out === "number" && <span>out:{e.telemetry.tokens_out}</span>}
              {typeof e.telemetry.latency_ms === "number" && <span>{e.telemetry.latency_ms}ms</span>}
              {typeof e.telemetry.cost_usd === "number" && <span>${e.telemetry.cost_usd.toFixed(6)}</span>}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", color: "var(--text-dim)", fontSize: 9 }}>
              {typeof e.telemetry.run_input_tokens === "number" && <span>run in:{e.telemetry.run_input_tokens}</span>}
              {typeof e.telemetry.run_output_tokens === "number" && <span>run out:{e.telemetry.run_output_tokens}</span>}
              {typeof e.telemetry.run_cost_usd === "number" && <span>run ${e.telemetry.run_cost_usd.toFixed(6)}</span>}
              {typeof e.telemetry.run_latency_ms === "number" && <span>run {e.telemetry.run_latency_ms}ms</span>}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", color: "var(--text-dim)", fontSize: 9 }}>
              {e.telemetry.start_time && <span>start:{new Date(e.telemetry.start_time).toLocaleTimeString()}</span>}
              {e.telemetry.end_time && <span>end:{new Date(e.telemetry.end_time).toLocaleTimeString()}</span>}
              {e.telemetry.timestamp && <span>recorded:{new Date(e.telemetry.timestamp).toLocaleTimeString()}</span>}
            </div>
            {e.telemetry.input_preview && (
              <div style={{ color: "var(--text-dim)", fontSize: 9, lineHeight: 1.4, border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "4px 6px", whiteSpace: "pre-wrap" }}>
                input: {e.telemetry.input_preview}
              </div>
            )}
            {e.telemetry.output_preview && (
              <div style={{ color: "var(--text-dim)", fontSize: 9, lineHeight: 1.4, border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "4px 6px", whiteSpace: "pre-wrap" }}>
                output: {e.telemetry.output_preview}
              </div>
            )}
            {e.telemetry.attributes && Object.keys(e.telemetry.attributes).length > 0 && (
              <div style={{ color: "var(--text-dim)", fontSize: 9, lineHeight: 1.4, border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "4px 6px", whiteSpace: "pre-wrap" }}>
                attrs: {JSON.stringify(e.telemetry.attributes)}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return null;
}

export function AgentGraph({ agentId, activeToolName, subAgents, onNavigateSubAgent, refreshTrigger }: AgentGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<AgentGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<number | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<DetailInfo | null>(null);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("pipeline");
  const [showPhaseColors, setShowPhaseColors] = useState(false);
  const [selectedPhaseId, setSelectedPhaseId] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());
  const selectedNodeIdsRef = useRef<Set<string>>(new Set());

  const [miniNodes, setMiniNodes] = useState<Array<{ id: string; x: number; y: number; phaseId?: string }>>([]);
  const [worldBounds, setWorldBounds] = useState({ minX: 0, maxX: W, minY: 0, maxY: H });
  const [zoomTransform, setZoomTransform] = useState(d3.zoomIdentity);
  const zoomTransformRef = useRef(d3.zoomIdentity);

  // Refs to live D3 selections so phase/opacity effects don't rebuild the SVG
  const nodeSelRef = useRef<d3.Selection<SVGGElement, D3Node, SVGGElement, unknown> | null>(null);
  const linkSelRef = useRef<d3.Selection<SVGPathElement, D3Link, SVGGElement, unknown> | null>(null);
  const hullLayerRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const nodesRef = useRef<D3Node[]>([]);

  const phaseColorMap = useMemo(() => {
    const ids = [
      ...(data?.phase_groups?.map((p) => p.phase_id) ?? []),
      ...(data?.nodes.map((n) => n.phase_id).filter(Boolean) ?? []),
      ...(data?.edges.map((e) => e.phase_id).filter(Boolean) ?? []),
    ] as string[];
    return buildPhaseColorMap(ids);
  }, [data]);

  useEffect(() => {
    selectedNodeIdsRef.current = selectedNodeIds;
  }, [selectedNodeIds]);

  // Lightweight phase opacity update — no SVG teardown
  useEffect(() => {
    const nodeSel = nodeSelRef.current;
    const linkSel = linkSelRef.current;
    if (!nodeSel || !linkSel) return;
    nodeSel.style("opacity", (d: D3Node) => (selectedPhaseId ? (d.phaseId === selectedPhaseId ? 1 : 0.24) : 1));
    linkSel.attr("opacity", (d: D3Link) => (selectedPhaseId ? (d.phaseId === selectedPhaseId ? 0.92 : 0.10) : 0.72));
    // Redraw hulls
    const hl = hullLayerRef.current;
    const nodes = nodesRef.current;
    if (hl && nodes.length > 0) {
      if (!showPhaseColors) { hl.selectAll("*").remove(); return; }
      const byPhase = new Map<string, [number, number][]>();
      for (const n of nodes) {
        if (!n.phaseId) continue;
        if (!byPhase.has(n.phaseId)) byPhase.set(n.phaseId, []);
        byPhase.get(n.phaseId)!.push([n.x ?? 0, n.y ?? 0]);
      }
      hl.selectAll("path").remove();
      hl.selectAll("circle").remove();
      byPhase.forEach((pts, phaseId) => {
        const color = phaseColor(phaseId, phaseColorMap);
        const opacity = selectedPhaseId ? (selectedPhaseId === phaseId ? 0.9 : 0.15) : 0.55;
        if (pts.length === 1) {
          hl.append("circle").attr("cx", pts[0][0]).attr("cy", pts[0][1]).attr("r", 58)
            .attr("fill", color.replace(")", ", 0.06)").replace("rgb", "rgba"))
            .attr("stroke", color).attr("stroke-width", 1).attr("stroke-dasharray", "5 3").attr("opacity", opacity);
          return;
        }
        let ptsForHull = pts;
        if (pts.length === 2) {
          ptsForHull = [pts[0], pts[1], [(pts[0][0] + pts[1][0]) / 2 + 1, (pts[0][1] + pts[1][1]) / 2 + 1]];
        }
        const hull = d3.polygonHull(ptsForHull);
        if (!hull) return;
        const cx = hull.reduce((s, p) => s + p[0], 0) / hull.length;
        const cy = hull.reduce((s, p) => s + p[1], 0) / hull.length;
        const pad = 52;
        const expandedHull = hull.map(([hx, hy]): [number, number] => {
          const dx = hx - cx; const dy = hy - cy;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return [hx + (dx / dist) * pad, hy + (dy / dist) * pad];
        });
        const lineGen = d3.line().curve(d3.curveCatmullRomClosed.alpha(0.5));
        hl.append("path").attr("d", lineGen(expandedHull) ?? "")
          .attr("fill", color.replace(")", ", 0.07)").replace("rgb", "rgba"))
          .attr("stroke", color).attr("stroke-width", 1.2).attr("stroke-dasharray", "6 3").attr("opacity", opacity);
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPhaseId, showPhaseColors]);

  const refreshGraph = useCallback(async (runId?: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const g = await getAgentGraph(agentId, runId ?? null);
      setData(g);
      if (g?.available_runs && g.available_runs.length > 0 && runId == null) {
        setSelectedRunId(g.available_runs[0].id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { refreshGraph(); }, [refreshGraph]);

  useEffect(() => {
    if (refreshTrigger) refreshGraph();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTrigger]);

  useEffect(() => {
    if (!data || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const nodes: D3Node[] = data.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      type: n.type,
      status: n.status,
      description: n.description,
      phaseId: n.phase_id,
      phaseName: n.phase_name,
    }));

    if (subAgents && subAgents.length > 0) {
      for (const sa of subAgents) {
        if (!nodes.find((n) => n.id === sa.agent_id)) {
          nodes.push({
            id: sa.agent_id,
            label: sa.name,
            type: "subagent",
            trustScore: sa.trust_score,
            tier: sa.current_tier,
            virtual: Boolean(sa.virtual),
          });
        }
      }
    }

    const nodeIds = new Set(nodes.map((n) => n.id));
    const links: D3Link[] = data.edges
      .filter((e) => nodeIds.has(e.from) && nodeIds.has(e.to))
      .map((e) => ({
        source: e.from,
        target: e.to,
        edgeType: e.type,
        sourceId: e.from,
        targetId: e.to,
        order: e.order,
        phaseId: e.phase_id,
        telemetry: e.telemetry,
      }));

    const agentNode = nodes.find((n) => n.type === "agent");
    if (agentNode && subAgents) {
      for (const sa of subAgents) {
        if (nodeIds.has(sa.agent_id)) {
          links.push({
            source: agentNode.id,
            target: sa.agent_id,
            edgeType: "delegates",
            sourceId: agentNode.id,
            targetId: sa.agent_id,
          });
        }
      }
    }

    const defs = svg.append("defs");
    const gridPattern = defs.append("pattern")
      .attr("id", "graph-grid")
      .attr("width", 28)
      .attr("height", 28)
      .attr("patternUnits", "userSpaceOnUse");
    gridPattern.append("path")
      .attr("d", "M 28 0 L 0 0 0 28")
      .attr("fill", "none")
      .attr("stroke", "rgba(100,116,139,0.10)")
      .attr("stroke-width", 1);
    ["uses", "blocked", "reads", "delegates", "sequence"].forEach((type) => {
      defs.append("marker")
        .attr("id", `arrow-${type}`)
        .attr("viewBox", "0 -4 8 8")
        .attr("refX", 7)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-3L8,0L0,3")
        .attr("fill", "currentColor");
    });

    svg.append("rect")
      .attr("x", 0)
      .attr("y", 0)
      .attr("width", W)
      .attr("height", H)
      .attr("fill", "rgba(2,6,23,0.35)");
    svg.append("rect")
      .attr("x", 0)
      .attr("y", 0)
      .attr("width", W)
      .attr("height", H)
      .attr("fill", "url(#graph-grid)");

    const container = svg.append("g");

    // ── Phase hull layer (drawn first so it sits beneath edges + nodes) ─────────
    // Groups nodes by phase and draws a soft rounded hull background per phase.
    const hullLayer = container.append("g").attr("class", "phase-hulls");
    hullLayerRef.current = hullLayer as unknown as d3.Selection<SVGGElement, unknown, null, undefined>;
    nodesRef.current = nodes;

    // Hull update function — called after node positions are set
    const updateHulls = () => {
      if (!showPhaseColors) { hullLayer.selectAll("*").remove(); return; }
      // Group node positions by phase
      const byPhase = new Map<string, [number, number][]>();
      for (const n of nodes) {
        if (!n.phaseId) continue;
        if (!byPhase.has(n.phaseId)) byPhase.set(n.phaseId, []);
        byPhase.get(n.phaseId)!.push([n.x ?? 0, n.y ?? 0]);
      }
      hullLayer.selectAll("path").remove();
      byPhase.forEach((pts, phaseId) => {
        const color = phaseColor(phaseId, phaseColorMap);
        // Need ≥3 points for hull; for 1-2 points render an ellipse instead
        if (pts.length === 1) {
          hullLayer.append("circle")
            .attr("cx", pts[0][0]).attr("cy", pts[0][1]).attr("r", 58)
            .attr("fill", color.replace(")", ", 0.06)").replace("rgb", "rgba"))
            .attr("stroke", color).attr("stroke-width", 1).attr("stroke-dasharray", "5 3")
            .attr("opacity", selectedPhaseId ? (selectedPhaseId === phaseId ? 0.9 : 0.15) : 0.55);
          return;
        }
        if (pts.length === 2) {
          pts = [pts[0], pts[1], [(pts[0][0] + pts[1][0]) / 2 + 1, (pts[0][1] + pts[1][1]) / 2 + 1]];
        }
        const hull = d3.polygonHull(pts);
        if (!hull) return;
        // Expand hull by padding
        const cx = hull.reduce((s, p) => s + p[0], 0) / hull.length;
        const cy = hull.reduce((s, p) => s + p[1], 0) / hull.length;
        const pad = 52;
        const expandedHull = hull.map(([hx, hy]): [number, number] => {
          const dx = hx - cx;
          const dy = hy - cy;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          return [hx + (dx / dist) * pad, hy + (dy / dist) * pad];
        });
        const lineGen = d3.line().curve(d3.curveCatmullRomClosed.alpha(0.5));
        hullLayer.append("path")
          .attr("d", lineGen(expandedHull) ?? "")
          .attr("fill", color.replace(")", ", 0.07)").replace("rgb", "rgba"))
          .attr("stroke", color)
          .attr("stroke-width", 1.2)
          .attr("stroke-dasharray", "6 3")
          .attr("opacity", selectedPhaseId ? (selectedPhaseId === phaseId ? 0.90 : 0.15) : 0.55);
      });
    };

    const edgeStroke = (d: D3Link) => (showPhaseColors && d.phaseId ? phaseColor(d.phaseId, phaseColorMap) : baseEdgeColor(d.edgeType));
    const edgeOpacity = (d: D3Link) => (selectedPhaseId ? (d.phaseId === selectedPhaseId ? 0.92 : 0.10) : 0.72);
    const nodeOpacity = (d: D3Node) => (selectedPhaseId ? (d.phaseId === selectedPhaseId ? 1 : 0.24) : 1);

    const updateMiniMeta = (transform: d3.ZoomTransform) => {
      const xs = nodes.map((n) => n.x ?? 0);
      const ys = nodes.map((n) => n.y ?? 0);
      const minX = Math.min(...xs, 0) - 40;
      const maxX = Math.max(...xs, W) + 40;
      const minY = Math.min(...ys, 0) - 40;
      const maxY = Math.max(...ys, H) + 40;
      setWorldBounds({ minX, maxX, minY, maxY });
      setMiniNodes(nodes.map((n) => ({ id: n.id, x: n.x ?? 0, y: n.y ?? 0, phaseId: n.phaseId })));
      setZoomTransform(transform);
    };

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.45, 3.2])
      .on("zoom", (event) => {
        container.attr("transform", event.transform);
        zoomTransformRef.current = event.transform;
        setZoomTransform(event.transform);
      });

    svg.call(zoom);

    const link = container.append("g")
      .selectAll<SVGPathElement, D3Link>("path")
      .data(links)
      .join("path")
      .attr("stroke", edgeStroke)
      .attr("color", edgeStroke)
      .attr("fill", "none")
      .attr("stroke-width", (d) => (d.edgeType === "blocked" ? 1.4 : d.edgeType === "sequence" ? 2.2 : d.edgeType === "delegates" ? 1.8 : 1.6))
      .attr("stroke-dasharray", (d) => (d.edgeType === "blocked" ? "5 3" : d.edgeType === "reads" ? "3 3" : d.edgeType === "delegates" ? "6 3" : "none"))
      .attr("marker-end", (d) => `url(#arrow-${d.edgeType})`)
      .attr("opacity", edgeOpacity)
      .style("cursor", "pointer")
      .on("click", (_event, d) => {
        const sNode = nodes.find((n) => n.id === d.sourceId);
        const tNode = nodes.find((n) => n.id === d.targetId);
        setDetail({ type: "edge", edge: d, sourceNode: sNode, targetNode: tNode });
      });
    linkSelRef.current = link as unknown as d3.Selection<SVGPathElement, D3Link, SVGGElement, unknown>;

    const selectionOverlay = svg.append("g").attr("class", "selection-overlay");
    if (selectionMode) {
      const brush = d3.brush()
        .extent([[0, 0], [W, H]])
        .on("end", (event) => {
          if (!event.selection) return;
          const [[sx0, sy0], [sx1, sy1]] = event.selection as [[number, number], [number, number]];
          const transform = zoomTransformRef.current;
          const x0 = transform.invertX(Math.min(sx0, sx1));
          const x1 = transform.invertX(Math.max(sx0, sx1));
          const y0 = transform.invertY(Math.min(sy0, sy1));
          const y1 = transform.invertY(Math.max(sy0, sy1));
          const ids = nodes
            .filter((n) => {
              const x = n.x ?? 0;
              const y = n.y ?? 0;
              return x >= x0 && x <= x1 && y >= y0 && y <= y1;
            })
            .map((n) => n.id);
          setSelectedNodeIds(new Set(ids));
          selectionOverlay.call(brush.move as never, null);
        });
      selectionOverlay.call(brush as never);
    }

    const node = container.append("g")
      .selectAll<SVGGElement, D3Node>("g")
      .data(nodes)
      .join("g")
      .style("cursor", (d) => (d.type === "subagent" && !d.virtual ? "pointer" : "default"))
      .style("opacity", nodeOpacity)
      .on("click", (_event, d) => {
        if (d.type === "subagent" && !d.virtual && onNavigateSubAgent) onNavigateSubAgent(d.id);
        else setDetail({ type: "node", node: d });
      });
    nodeSelRef.current = node as unknown as d3.Selection<SVGGElement, D3Node, SVGGElement, unknown>;

    node.append("circle")
      .attr("class", "selection-ring")
      .attr("r", (d) => (NODE_SIZES[d.type] || 18) + 10)
      .attr("fill", "none")
      .attr("stroke", "rgba(245,158,11,0.82)")
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "4 3")
      .style("display", (d) => (selectedNodeIdsRef.current.has(d.id) ? "block" : "none"));

    node.filter((d) => d.type === "agent").each(function (d) {
      const g = d3.select(this);
      const s = NODE_SIZES.agent;
      // Subtle glow behind the agent node
      g.append("rect")
        .attr("x", -s - 4).attr("y", -s - 4).attr("width", (s + 4) * 2).attr("height", (s + 4) * 2).attr("rx", 10)
        .attr("fill", "rgba(245,158,11,0.05)")
        .attr("stroke", "none");
      g.append("rect")
        .attr("x", -s).attr("y", -s).attr("width", s * 2).attr("height", s * 2).attr("rx", 8)
        .attr("fill", NODE_COLORS.agent.fill)
        .attr("stroke", showPhaseColors && d.phaseId ? phaseColor(d.phaseId, phaseColorMap) : NODE_COLORS.agent.stroke)
        .attr("stroke-width", 2.0);
      g.append("text").text("AGENT").attr("text-anchor", "middle").attr("y", -10).attr("font-size", 8.5).attr("fill", "rgba(245,158,11,0.82)").attr("font-family", "var(--font-mono)").attr("letter-spacing", "0.08em");
      g.append("text").text(d.label.length > 18 ? `${d.label.slice(0, 16)}…` : d.label).attr("text-anchor", "middle").attr("y", 12).attr("font-size", 12).attr("font-weight", "600").attr("fill", "#f5f5f5").attr("font-family", "var(--font-mono)");
    });

    node.filter((d) => d.type === "tool").each(function (d) {
      const g = d3.select(this);
      const r = NODE_SIZES.tool;
      const colors = getNodeColor(d);
      g.append("circle").attr("r", r)
        .attr("fill", colors.fill)
        .attr("stroke", showPhaseColors && d.phaseId ? phaseColor(d.phaseId, phaseColorMap) : colors.stroke)
        .attr("stroke-width", 1.7);
      // Label: show up to 16 chars for better readability
      g.append("text").text(d.label.replace(/[()]/g, "").slice(0, 16)).attr("text-anchor", "middle").attr("y", 4).attr("font-size", 9).attr("fill", colors.text).attr("font-family", "var(--font-mono)");
    });

    node.filter((d) => d.type === "model").each(function (d) {
      const g = d3.select(this);
      const colors = getNodeColor(d);
      g.append("rect").attr("x", -44).attr("y", -15).attr("width", 88).attr("height", 30).attr("rx", 7)
        .attr("fill", colors.fill)
        .attr("stroke", showPhaseColors && d.phaseId ? phaseColor(d.phaseId, phaseColorMap) : colors.stroke)
        .attr("stroke-width", 1.6);
      g.append("text").text(d.label.length > 16 ? `${d.label.slice(0, 14)}…` : d.label).attr("text-anchor", "middle").attr("y", 5).attr("font-size", 9).attr("fill", colors.text).attr("font-family", "var(--font-mono)");
    });

    node.filter((d) => d.type === "data").each(function (d) {
      const g = d3.select(this);
      const colors = getNodeColor(d);
      g.append("rect").attr("x", -36).attr("y", -13).attr("width", 72).attr("height", 26).attr("rx", 5)
        .attr("fill", colors.fill)
        .attr("stroke", showPhaseColors && d.phaseId ? phaseColor(d.phaseId, phaseColorMap) : colors.stroke)
        .attr("stroke-width", 1.4);
      g.append("text").text(d.label.length > 16 ? `${d.label.slice(0, 14)}…` : d.label).attr("text-anchor", "middle").attr("y", 5).attr("font-size", 8).attr("fill", colors.text).attr("font-family", "var(--font-mono)");
    });

    node.filter((d) => d.type === "subagent").each(function (d) {
      const g = d3.select(this);
      const r = NODE_SIZES.subagent;
      const points = `0,${-r} ${r * 0.9},0 0,${r} ${-r * 0.9},0`;
      g.append("polygon").attr("points", points)
        .attr("fill", NODE_COLORS.subagent.fill)
        .attr("stroke", showPhaseColors && d.phaseId ? phaseColor(d.phaseId, phaseColorMap) : NODE_COLORS.subagent.stroke)
        .attr("stroke-width", 1.7);
      g.append("text").text(d.label.length > 12 ? `${d.label.slice(0, 10)}…` : d.label).attr("text-anchor", "middle").attr("y", 4).attr("font-size", 9).attr("fill", NODE_COLORS.subagent.text).attr("font-family", "var(--font-mono)");
    });

    const setLinkPositions = () => {
      link
        .attr("d", (d) => edgePath(d, nodes))
        .attr("opacity", edgeOpacity)
        .attr("stroke", edgeStroke)
        .attr("color", edgeStroke);
    };

    const setNodePositions = () => {
      node.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`).style("opacity", nodeOpacity);
      node.selectAll<SVGCircleElement, D3Node>(".selection-ring")
        .style("display", (d) => (selectedNodeIdsRef.current.has(d.id) ? "block" : "none"));
      updateHulls();
      setLinkPositions();
      updateMiniMeta(zoomTransformRef.current);
    };

    const fitGraphToViewport = () => {
      const xs = nodes.map((n) => n.x ?? 0);
      const ys = nodes.map((n) => n.y ?? 0);
      if (xs.length === 0 || ys.length === 0) return;

      const maxNodeR = Math.max(...nodes.map((n) => nodeRadius(n)), 24);
      const minX = Math.min(...xs) - maxNodeR;
      const maxX = Math.max(...xs) + maxNodeR;
      const minY = Math.min(...ys) - maxNodeR;
      const maxY = Math.max(...ys) + maxNodeR;
      const contentW = Math.max(1, maxX - minX);
      const contentH = Math.max(1, maxY - minY);
      const pad = 44;
      const scale = Math.max(0.55, Math.min(2.2, 0.96 * Math.min(W / (contentW + pad), H / (contentH + pad))));

      const tx = W / 2 - scale * (minX + contentW / 2);
      const ty = H / 2 - scale * (minY + contentH / 2);
      const t = d3.zoomIdentity.translate(tx, ty).scale(scale);
      svg.transition().duration(120).call(zoom.transform, t);
    };

    let particleTimer: d3.Timer | null = null;
    let simulation: d3.Simulation<D3Node, D3Link> | null = null;
    let cancelled = false;

    node.call(
      d3.drag<SVGGElement, D3Node>()
        .on("start", (event, d) => {
          if (simulation && !event.active) simulation.alphaTarget(0.25).restart();
          if (!selectedNodeIdsRef.current.has(d.id)) {
            setSelectedNodeIds(new Set([d.id]));
          }
          nodes.forEach((n) => {
            if (selectedNodeIdsRef.current.has(n.id) || n.id === d.id) {
              n.fx = n.x;
              n.fy = n.y;
            }
          });
        })
        .on("drag", (event, d) => {
          const dragIds = new Set(selectedNodeIdsRef.current.has(d.id) ? selectedNodeIdsRef.current : [d.id]);
          nodes.forEach((n) => {
            if (dragIds.has(n.id)) {
              n.x = (n.x ?? 0) + event.dx;
              n.y = (n.y ?? 0) + event.dy;
              n.fx = n.x;
              n.fy = n.y;
            }
          });
          setNodePositions();
        })
        .on("end", (event, d) => {
          if (simulation && !event.active) simulation.alphaTarget(0);
          const dragIds = new Set(selectedNodeIdsRef.current.has(d.id) ? selectedNodeIdsRef.current : [d.id]);
          if (layoutMode === "explore") {
            nodes.forEach((n) => {
              if (dragIds.has(n.id)) {
                n.fx = null;
                n.fy = null;
              }
            });
          } else {
            nodes.forEach((n) => {
              if (dragIds.has(n.id)) {
                n.fx = n.x;
                n.fy = n.y;
              }
            });
          }
        }),
    );

    const runPipelineLayout = async () => {
      const sequence = links
        .filter((l) => l.edgeType === "sequence" && typeof l.order === "number")
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

      if (sequence.length > 0) {
        const orderByNode = new Map<string, number>();
        for (const edge of sequence) {
          if (typeof edge.order === "number") {
            orderByNode.set(edge.targetId, edge.order);
          }
        }

        const uniqueOrders = Array.from(new Set(Array.from(orderByNode.values()).filter((v) => Number.isFinite(v)))).sort((a, b) => a - b);
        const orderColumn = new Map<number, number>();
        uniqueOrders.forEach((order, idx) => orderColumn.set(order, idx + 1));

        const columnFor = (nodeRef: D3Node): number => {
          const rawOrder = orderByNode.get(nodeRef.id);
          if (rawOrder !== undefined) return orderColumn.get(rawOrder) ?? 1;
          return uniqueOrders.length + 1;
        };

        const columnCount = Math.max(2, uniqueOrders.length + 1);
        const stepX = Math.max(84, Math.min(112, (W - 220) / columnCount));
        const startX = 140;

        const laneOrder: D3Node["type"][] = ["agent", "tool", "model", "data", "subagent"];
        const laneY = new Map<D3Node["type"], number>();
        const laneGap = 104;
        const topY = H / 2 - ((laneOrder.length - 1) * laneGap) / 2;
        laneOrder.forEach((lane, idx) => laneY.set(lane, topY + idx * laneGap));

        const bucketedByOrderAndLane = new Map<string, D3Node[]>();
        const phaseIds = data.phase_groups?.map((p) => p.phase_id) ?? [];
        const phaseRank = new Map<string, number>();
        phaseIds.forEach((pid, idx) => phaseRank.set(pid, idx));

        const addToBucket = (nodeRef: D3Node, order: number) => {
          const key = `${order}:${nodeRef.type}`;
          const bucket = bucketedByOrderAndLane.get(key) || [];
          bucket.push(nodeRef);
          bucketedByOrderAndLane.set(key, bucket);
        };

        const root = nodes.find((n) => n.id === "agent");
        if (root) {
          root.x = 78;
          root.y = laneY.get("agent") ?? H / 2;
          root.fx = root.x;
          root.fy = root.y;
        }

        nodes.forEach((n) => {
          if (n.id === "agent") return;
          const order = columnFor(n);
          addToBucket(n, order);
        });

        bucketedByOrderAndLane.forEach((bucket, compositeKey) => {
          const [orderText, laneText] = compositeKey.split(":");
          const order = Number(orderText);
          const lane = laneText as D3Node["type"];
          const baseY = laneY.get(lane) ?? H / 2;
          const columnX = startX + Math.max(0, order - 1) * stepX;

          bucket.sort((a, b) => {
            const pa = phaseRank.get(a.phaseId ?? "") ?? Number.MAX_SAFE_INTEGER;
            const pb = phaseRank.get(b.phaseId ?? "") ?? Number.MAX_SAFE_INTEGER;
            if (pa !== pb) return pa - pb;
            return a.id.localeCompare(b.id);
          });

          const spread = lane === "tool" ? 28 : 24;
          bucket.forEach((nodeRef, idx) => {
            const offset = (idx - (bucket.length - 1) / 2) * spread;
            nodeRef.x = columnX;
            nodeRef.y = baseY + offset;
            nodeRef.fx = nodeRef.x;
            nodeRef.fy = nodeRef.y;
          });
        });
      } else {
        const elk = new ELK();
        const layouted = await elk.layout({
          id: "root",
          layoutOptions: {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.edgeRouting": "SPLINES",
            "elk.spacing.nodeNode": "88",
            "elk.layered.spacing.edgeNodeBetweenLayers": "96",
            "elk.layered.spacing.nodeNodeBetweenLayers": "100",
            "elk.nodePlacement.strategy": "BRANDES_KOEPF",
            "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
            "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
          },
          children: nodes.map((n) => ({
            id: n.id,
            width: (NODE_SIZES[n.type] || 20) * 2 + 36,
            height: (NODE_SIZES[n.type] || 20) * 2 + 18,
          })),
          edges: links.map((l, i) => ({ id: `e${i}`, sources: [l.sourceId], targets: [l.targetId] })),
        });
        if (cancelled || !layouted.children) return;

        layouted.children.forEach((en) => {
          const nodeRef = nodes.find((k) => k.id === en.id);
          if (nodeRef && en.x !== undefined && en.y !== undefined) {
            nodeRef.x = en.x + (en.width || 0) / 2;
            nodeRef.y = en.y + (en.height || 0) / 2;
            nodeRef.fx = nodeRef.x;
            nodeRef.fy = nodeRef.y;
          }
        });
      }

      setNodePositions();
      fitGraphToViewport();
    };

    const runExploreLayout = () => {
      simulation = d3.forceSimulation<D3Node>(nodes)
        .alphaDecay(0.04)
        .force("link", d3.forceLink<D3Node, D3Link>(links).id((d) => d.id).distance((d) => {
          if (d.edgeType === "sequence") return 145;
          if (d.edgeType === "reads") return 100;
          if (d.edgeType === "delegates") return 200;
          return 150;
        }))
        .force("charge", d3.forceManyBody().strength((d) => ((d as D3Node).type === "agent" ? -780 : -300)))
        .force("center", d3.forceCenter(W / 2, H / 2))
        .force("collision", d3.forceCollide().radius((d) => (NODE_SIZES[(d as D3Node).type] || 18) + 24));

      let tickCount = 0;
      simulation.on("tick", () => {
        tickCount++;
        nodes.forEach((n) => {
          n.x = Math.max(20, Math.min(W - 20, n.x ?? 0));
          n.y = Math.max(20, Math.min(H - 20, n.y ?? 0));
        });
        // Only update DOM every 3 ticks to reduce layout thrash
        if (tickCount % 3 === 0) {
          node.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
          link.attr("d", (d) => edgePath(d, nodes));
        }
      });

      simulation.on("end", () => {
        if (!cancelled) {
          setNodePositions();
          fitGraphToViewport();
        }
      });

      setTimeout(() => {
        if (!cancelled) fitGraphToViewport();
      }, 500);
    };

    if (layoutMode === "explore") {
      const animatedEdges = links.filter((lnk) => lnk.edgeType !== "blocked" && lnk.edgeType !== "sequence").slice(0, 16);
      particleTimer = d3.interval(() => {
        animatedEdges.forEach((lnk) => {
          const src = nodes.find((n) => n.id === lnk.sourceId);
          const tgt = nodes.find((n) => n.id === lnk.targetId);
          if (!src?.x || !src?.y || !tgt?.x || !tgt?.y) return;
          const particle = container.append("circle")
            .attr("r", 2)
            .attr("fill", edgeStroke(lnk))
            .attr("opacity", 0.7)
            .attr("cx", src.x)
            .attr("cy", src.y);
          particle.transition().duration(1650 + Math.random() * 450).ease(d3.easeLinear).attr("cx", tgt.x).attr("cy", tgt.y).attr("opacity", 0).remove();
        });
      }, 3200);
    }

    if (layoutMode === "pipeline") runPipelineLayout();
    else runExploreLayout();

    node.on("mouseenter", function (_, d) {
      link.attr("opacity", (l) => (l.sourceId === d.id || l.targetId === d.id ? 1 : 0.15));
    }).on("mouseleave", () => {
      link.attr("opacity", edgeOpacity);
      node.style("opacity", nodeOpacity);
    });

    return () => {
      cancelled = true;
      if (particleTimer) particleTimer.stop();
      if (simulation) simulation.stop();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, subAgents, onNavigateSubAgent, layoutMode, selectionMode]);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll<SVGCircleElement, D3Node>(".selection-ring")
      .style("display", (d) => (selectedNodeIds.has(d.id) ? "block" : "none"));
  }, [selectedNodeIds]);

  useEffect(() => {
    if (!svgRef.current || !data || !activeToolName) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll<SVGGElement, D3Node>("g g").each(function (d) {
      const g = d3.select(this);
      const isActive = d.id === activeToolName || d.label === activeToolName || d.label.replace("()", "") === activeToolName;
      if (d.type === "tool") {
        g.select("circle").attr("stroke-width", isActive ? 2.7 : 1.4);
      }
    });
  }, [activeToolName, data]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "20px 0", color: "var(--text-dim)", fontSize: 10, fontFamily: "var(--font-mono)" }}>
        <span style={{ animation: "spin 1s linear infinite", display: "inline-block" }}>◌</span>
        Loading agent structure…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ padding: "12px", background: "rgba(239,68,68,0.05)", border: "1px solid rgba(239,68,68,0.15)", borderRadius: "var(--radius-sm)", fontSize: 10, color: "var(--red)", fontFamily: "var(--font-mono)" }}>
        {error ?? "No graph data available"}
        <button onClick={() => refreshGraph()} style={{ marginLeft: 12, all: "unset", cursor: "pointer", color: "var(--text-dim)", textDecoration: "underline" }}>retry</button>
      </div>
    );
  }

  const phaseGroups = data.phase_groups ?? [];
  const selectedTaskData = selectedTask !== null && data.tasks[selectedTask] ? data.tasks[selectedTask] : null;

  const rangeX = Math.max(1, worldBounds.maxX - worldBounds.minX);
  const rangeY = Math.max(1, worldBounds.maxY - worldBounds.minY);
  const mapX = (x: number) => ((x - worldBounds.minX) / rangeX) * MINIMAP_W;
  const mapY = (y: number) => ((y - worldBounds.minY) / rangeY) * MINIMAP_H;

  const vx0 = (0 - zoomTransform.x) / zoomTransform.k;
  const vy0 = (0 - zoomTransform.y) / zoomTransform.k;
  const vx1 = (W - zoomTransform.x) / zoomTransform.k;
  const vy1 = (H - zoomTransform.y) / zoomTransform.k;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ background: "var(--bg-1)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", overflow: "hidden", position: "relative" }}>
        <div style={{ position: "absolute", top: 8, left: 10, display: "flex", gap: 10, fontSize: 8, fontFamily: "var(--font-mono)", color: "var(--text-dim)", zIndex: 8 }}>
          <span style={{ color: "var(--green)" }}>● {data.nodes.filter((n) => n.type === "tool" && n.status !== "denied").length} allowed</span>
          <span style={{ color: "var(--red)" }}>● {data.nodes.filter((n) => n.type === "tool" && n.status === "denied").length} denied</span>
          {phaseGroups.length > 0 && <span style={{ color: "var(--amber)" }}>phase groups: {phaseGroups.length}</span>}
        </div>

        <div style={{ position: "absolute", top: 8, right: 10, zIndex: 9, display: "flex", alignItems: "center", gap: 8 }}>
          <button onClick={() => setLayoutMode("pipeline")} style={{ padding: "2px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: layoutMode === "pipeline" ? "var(--bg-4)" : "transparent", color: layoutMode === "pipeline" ? "var(--amber)" : "var(--text-dim)", fontSize: 9, fontFamily: "var(--font-mono)", cursor: "pointer" }}>PIPELINE</button>
          <button onClick={() => setLayoutMode("explore")} style={{ padding: "2px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: layoutMode === "explore" ? "var(--bg-4)" : "transparent", color: layoutMode === "explore" ? "var(--amber)" : "var(--text-dim)", fontSize: 9, fontFamily: "var(--font-mono)", cursor: "pointer" }}>EXPLORE</button>
          <button onClick={() => setShowPhaseColors((v) => !v)} style={{ padding: "2px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: showPhaseColors ? "var(--bg-4)" : "transparent", color: showPhaseColors ? "var(--amber)" : "var(--text-dim)", fontSize: 9, fontFamily: "var(--font-mono)", cursor: "pointer" }}>PHASE COLOR</button>
          <button onClick={() => setSelectionMode((v) => !v)} style={{ padding: "2px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: selectionMode ? "var(--bg-4)" : "transparent", color: selectionMode ? "var(--amber)" : "var(--text-dim)", fontSize: 9, fontFamily: "var(--font-mono)", cursor: "pointer" }}>BOX SELECT</button>
          {selectedNodeIds.size > 0 && (
            <button onClick={() => setSelectedNodeIds(new Set())} style={{ padding: "2px 8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-default)", background: "transparent", color: "var(--text-dim)", fontSize: 9, fontFamily: "var(--font-mono)", cursor: "pointer" }}>CLEAR ({selectedNodeIds.size})</button>
          )}
          {data.available_runs && data.available_runs.length > 0 && (
            <select value={selectedRunId ?? ""} onChange={(e) => { const id = Number(e.target.value); setSelectedRunId(id); refreshGraph(id); }} style={{ background: "var(--bg-2)", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", fontSize: 9, padding: "2px 6px" }}>
              {data.available_runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.status}</option>)}
            </select>
          )}
        </div>

        {detail && <DetailPanel detail={detail} onClose={() => setDetail(null)} />}

        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block", maxHeight: 500 }} />

        <div style={{ position: "absolute", right: 10, bottom: 10, width: MINIMAP_W + 8, background: "rgba(15,23,42,0.75)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: 4, zIndex: 10 }}>
          <svg width={MINIMAP_W} height={MINIMAP_H} style={{ display: "block" }}>
            {miniNodes.map((n) => <circle key={n.id} cx={mapX(n.x)} cy={mapY(n.y)} r={2.2} fill={phaseColor(n.phaseId, phaseColorMap)} opacity={0.95} />)}
            <rect x={mapX(vx0)} y={mapY(vy0)} width={Math.max(4, mapX(vx1) - mapX(vx0))} height={Math.max(4, mapY(vy1) - mapY(vy0))} fill="none" stroke="rgba(245,158,11,0.8)" strokeWidth={1} />
          </svg>
          <div style={{ fontSize: 8, color: "var(--text-dim)", fontFamily: "var(--font-mono)", marginTop: 2 }}>overview map</div>
        </div>
      </div>

      {phaseGroups.length > 0 && (
        <div style={{ border: "1px solid var(--border-default)", borderRadius: "var(--radius-md)", background: "var(--bg-2)", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
            Workflow phases{data.phase_label_source ? ` · source: ${data.phase_label_source}` : ""}
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {phaseGroups.map((p) => (
              <button
                key={p.phase_id}
                onClick={() => setSelectedPhaseId((curr) => (curr === p.phase_id ? null : p.phase_id))}
                style={{ all: "unset", cursor: "pointer", border: `1px solid ${phaseColor(p.phase_id, phaseColorMap)}55`, background: `${phaseColor(p.phase_id, phaseColorMap)}18`, color: "var(--text-secondary)", borderRadius: "var(--radius-sm)", padding: "4px 8px", fontSize: 9, fontFamily: "var(--font-mono)", boxShadow: selectedPhaseId === p.phase_id ? `inset 0 0 0 1px ${phaseColor(p.phase_id, phaseColorMap)}` : "none" }}
              >
                <span style={{ color: phaseColor(p.phase_id, phaseColorMap) }}>●</span> {p.phase_name} · {p.span_ids.length} span{p.span_ids.length !== 1 ? "s" : ""}
                {selectedPhaseId === p.phase_id ? " · selected" : ""}
              </button>
            ))}
            {selectedPhaseId && (
              <button onClick={() => setSelectedPhaseId(null)} style={{ all: "unset", cursor: "pointer", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", padding: "4px 8px", fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                Clear highlight
              </button>
            )}
          </div>
        </div>
      )}

      {data.tasks.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 9, color: "var(--text-dim)", fontFamily: "var(--font-mono)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 2 }}>
            Task sequence · click to highlight
          </div>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {data.tasks.map((task, i) => {
              const isSelected = selectedTask === i;
              return (
                <button key={i} onClick={() => setSelectedTask(isSelected ? null : i)} style={{ all: "unset", cursor: "pointer", display: "flex", alignItems: "center", gap: 5, padding: "4px 8px", background: isSelected ? "rgba(245,158,11,0.12)" : "var(--bg-1)", border: `1px solid ${isSelected ? "rgba(245,158,11,0.4)" : "var(--border-default)"}`, borderRadius: "var(--radius-sm)", fontSize: 9, fontFamily: "var(--font-mono)", color: isSelected ? "var(--amber)" : "var(--text-secondary)", transition: "all 0.15s" }}>
                  <span style={{ color: "var(--text-dim)" }}>{i + 1}</span>
                  <span>{task.tool}</span>
                </button>
              );
            })}
          </div>
          {selectedTaskData && (
            <div style={{ padding: "8px 10px", background: "rgba(245,158,11,0.04)", border: "1px solid rgba(245,158,11,0.15)", borderRadius: "var(--radius-sm)", fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", lineHeight: 1.5 }}>
              <span style={{ color: "var(--amber)" }}>task {(selectedTask ?? 0) + 1}: </span>
              {selectedTaskData.description ?? `calls ${selectedTaskData.tool}`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
