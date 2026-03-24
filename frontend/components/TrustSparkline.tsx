import type { TrustPoint } from "@/lib/types";

interface Props {
  data: TrustPoint[];
  width?: number;
  height?: number;
}

const EVENT_COLORS: Record<string, string> = {
  violation: "#ef4444",
  tier_up: "#f59e0b",
  tier_down: "#ef4444",
  approved: "#22c55e",
};

export function TrustSparkline({ data, width = 120, height = 32 }: Props) {
  if (!data || data.length < 2) return null;

  const scores = data.map((d) => d.score);
  const minS = Math.min(...scores) - 0.02;
  const maxS = Math.max(...scores) + 0.02;
  const range = maxS - minS;

  const px = (i: number) => (i / (data.length - 1)) * width;
  const py = (s: number) => height - ((s - minS) / range) * height;

  const points = data.map((d, i) => `${px(i)},${py(d.score)}`).join(" ");

  // Gradient fill path
  const fillPath =
    `M ${px(0)},${height} ` +
    data.map((d, i) => `L ${px(i)},${py(d.score)}`).join(" ") +
    ` L ${px(data.length - 1)},${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block", overflow: "visible" }}
    >
      <defs>
        <linearGradient id={`sparkg-${width}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#f59e0b" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Fill */}
      <path d={fillPath} fill={`url(#sparkg-${width})`} />

      {/* Line */}
      <polyline
        points={points}
        fill="none"
        stroke="#f59e0b"
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* Event dots */}
      {data.map((d, i) =>
        d.event ? (
          <circle
            key={i}
            cx={px(i)}
            cy={py(d.score)}
            r={3}
            fill={EVENT_COLORS[d.event] ?? "#f59e0b"}
            stroke="var(--bg-2)"
            strokeWidth={1}
          />
        ) : null
      )}

      {/* Last point dot */}
      <circle
        cx={px(data.length - 1)}
        cy={py(data[data.length - 1].score)}
        r={2.5}
        fill="#f59e0b"
      />
    </svg>
  );
}
