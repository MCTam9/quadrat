"use client";

import { useMemo } from "react";
import { COMPASS16, WIND_BIN_LABELS, WIND_COLOURS, type WindRose } from "@/lib/climate";
import { hourCurve, pathD, projectSky, SUN_DAYS, sunArc } from "@/lib/sunpath";

export const SUN_COLOURS: Record<string, string> = { jun: "#d97706", equ: "#7c6fb0", dec: "#2563eb" };
const HALO = { paintOrder: "stroke", strokeLinejoin: "round" } as const;

interface Ink {
  ink: string;
  halo: string;
  grid: string;
}

/** Everything is drawn in a 100-unit disc (R = 100) centred on 0,0; strokes are screen pixels, text is sized by `scale`. */
export function SunPathLayer({
  lat,
  lon,
  offsetH,
  scale = 1,
  labels = true,
  ink,
  nowSun,
}: {
  lat: number;
  lon: number;
  offsetH: number;
  scale?: number;
  labels?: boolean;
  nowSun?: { azimuth: number; altitude: number } | null;
} & { ink: Ink }) {
  const R = 100;
  const geo = useMemo(() => {
    const arcs = SUN_DAYS.map((d) => sunArc(d, lat, lon, offsetH, R));
    const curves = [6, 8, 10, 12, 14, 16, 18].map((h) => hourCurve(h, lat, lon, offsetH, R));
    return { arcs, curves };
  }, [lat, lon, offsetH]);
  const fs = (px: number) => px / scale;
  return (
    <g>
      <circle r={R} fill="none" stroke={ink.grid} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      {[30, 60].map((a) => (
        <circle key={a} r={projectSky(0, a, R).y * -1} fill="none" stroke={ink.grid} strokeWidth={0.75} strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
      ))}
      {[0, 45, 90, 135].map((a) => {
        const p = projectSky(a, 0, R);
        return <line key={a} x1={-p.x} y1={-p.y} x2={p.x} y2={p.y} stroke={ink.grid} strokeWidth={0.75} vectorEffect="non-scaling-stroke" />;
      })}
      {geo.curves.flat().map((seg, i) => (
        <path key={i} d={pathD(seg)} fill="none" stroke={ink.grid} strokeWidth={1} opacity={0.9} vectorEffect="non-scaling-stroke" />
      ))}
      {geo.arcs.map((a) => (
        <g key={a.id} stroke={SUN_COLOURS[a.id]} fill={SUN_COLOURS[a.id]}>
          {a.segments.map((seg, i) => (
            <path key={i} d={pathD(seg)} fill="none" strokeWidth={2} vectorEffect="non-scaling-stroke" />
          ))}
          {a.hours.map((h) => (
            <circle key={h.hour} cx={h.pt.x} cy={h.pt.y} r={fs(2.2)} stroke={ink.halo} strokeWidth={1} vectorEffect="non-scaling-stroke">
              <title>{`${a.label}, ${String(h.hour).padStart(2, "0")}:00 local standard time`}</title>
            </circle>
          ))}
        </g>
      ))}
      {labels &&
        geo.arcs.map((a) => {
          const noon = a.hours.find((h) => h.hour === 12);
          if (!noon) return null;
          return (
            <text key={a.id} x={noon.pt.x} y={noon.pt.y + (a.id === "dec" ? fs(-8) : fs(14))} fontSize={fs(10)} textAnchor="middle" fill={SUN_COLOURS[a.id]} stroke={ink.halo} strokeWidth={fs(3)} style={HALO}>
              {a.label}
            </text>
          );
        })}
      {(["N", "E", "S", "W"] as const).map((c, i) => {
        const p = projectSky(i * 90, 0, R * 1.0);
        const q = { x: p.x * 1.11, y: p.y * 1.11 + fs(3.5) };
        return (
          <text key={c} x={q.x} y={q.y} fontSize={fs(11)} fontWeight={600} textAnchor="middle" fill={ink.ink} stroke={ink.halo} strokeWidth={fs(3)} style={HALO}>
            {c}
          </text>
        );
      })}
      {nowSun && nowSun.altitude > 0 && <NowSun sun={nowSun} scale={scale} ink={ink} />}
    </g>
  );
}

function NowSun({ sun, scale, ink }: { sun: { azimuth: number; altitude: number }; scale: number; ink: Ink }) {
  const R = 100;
  const edge = projectSky(sun.azimuth, 0, R);
  const tail = { x: -edge.x * 0.45, y: -edge.y * 0.45 };
  const p = projectSky(sun.azimuth, sun.altitude, R);
  return (
    <g>
      <line x1={0} y1={0} x2={edge.x} y2={edge.y} stroke="#f59e0b" strokeWidth={2.5} vectorEffect="non-scaling-stroke" opacity={0.9} />
      <line x1={0} y1={0} x2={tail.x} y2={tail.y} stroke={ink.ink} strokeWidth={1.5} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" opacity={0.7} />
      <circle cx={p.x} cy={p.y} r={6 / scale} fill="#fbbf24" stroke={ink.ink} strokeWidth={1.5} vectorEffect="non-scaling-stroke">
        <title>{`Sun now: azimuth ${sun.azimuth.toFixed(0)} deg, altitude ${sun.altitude.toFixed(0)} deg`}</title>
      </circle>
    </g>
  );
}

/** Wind rose in a 100-unit disc. Petals point toward the direction the wind blows FROM. */
export function WindRoseLayer({
  rose,
  scale = 1,
  labels = true,
  ink,
}: {
  rose: WindRose;
  scale?: number;
  labels?: boolean;
} & { ink: Ink }) {
  const R = 100;
  const fs = (px: number) => px / scale;
  const totals = rose.share.map((r) => r.reduce((a, b) => a + b, 0));
  const maxShare = Math.max(0.0001, ...totals);
  // round the axis max up to a "nice" step so rings read as whole percentages
  const step = maxShare > 0.2 ? 0.1 : maxShare > 0.1 ? 0.05 : 0.02;
  const axis = Math.ceil(maxShare / step) * step;
  const rad = (share: number) => (share / axis) * R;
  const pt = (angDeg: number, r: number) => {
    const a = (angDeg * Math.PI) / 180;
    return [r * Math.sin(a), -r * Math.cos(a)] as const;
  };
  const wedge = (centre: number, r0: number, r1: number) => {
    const half = 9;
    const [x0a, y0a] = pt(centre - half, r0);
    const [x0b, y0b] = pt(centre + half, r0);
    const [x1a, y1a] = pt(centre - half, r1);
    const [x1b, y1b] = pt(centre + half, r1);
    return `M${x0a} ${y0a}L${x1a} ${y1a}A${r1} ${r1} 0 0 1 ${x1b} ${y1b}L${x0b} ${y0b}A${r0} ${r0} 0 0 0 ${x0a} ${y0a}Z`;
  };
  const rings: number[] = [];
  for (let v = step; v <= axis + 1e-9; v += step) rings.push(v);
  return (
    <g>
      {rings.map((v, i) => (
        <g key={v}>
          <circle r={rad(v)} fill="none" stroke={ink.grid} strokeWidth={0.75} strokeDasharray={i === rings.length - 1 ? undefined : "2 3"} vectorEffect="non-scaling-stroke" />
          {labels && (
            <text x={2} y={-rad(v) - fs(1.5)} fontSize={fs(8.5)} fill={ink.ink} opacity={0.75} stroke={ink.halo} strokeWidth={fs(2.5)} style={HALO}>
              {Math.round(v * 100)}%
            </text>
          )}
        </g>
      ))}
      {[0, 45, 90, 135].map((a) => {
        const [x, y] = pt(a, R);
        return <line key={a} x1={-x} y1={-y} x2={x} y2={y} stroke={ink.grid} strokeWidth={0.75} vectorEffect="non-scaling-stroke" />;
      })}
      {rose.share.map((bins, d) => {
        let acc = 0;
        return (
          <g key={d}>
            {bins.map((v, b) => {
              if (v <= 0) return null;
              const r0 = rad(acc);
              acc += v;
              const r1 = rad(acc);
              return (
                <path key={b} d={wedge(d * 22.5, r0, r1)} fill={WIND_COLOURS[b]} stroke={ink.halo} strokeWidth={0.75} vectorEffect="non-scaling-stroke">
                  <title>{`From ${COMPASS16[d]}, ${WIND_BIN_LABELS[b]} m/s: ${(v * 100).toFixed(1)}% of hours`}</title>
                </path>
              );
            })}
          </g>
        );
      })}
      {labels &&
        COMPASS16.filter((_, i) => i % 4 === 0).map((c, i) => {
          const [x, y] = pt(i * 90, R * 1.1);
          return (
            <text key={c} x={x} y={y + fs(3.5)} fontSize={fs(11)} fontWeight={600} textAnchor="middle" fill={ink.ink} stroke={ink.halo} strokeWidth={fs(3)} style={HALO}>
              {c}
            </text>
          );
        })}
    </g>
  );
}

export const PANEL_INK: Ink = { ink: "var(--fg)", halo: "var(--surface, #fff)", grid: "var(--line)" };
export const MAP_INK: Ink = { ink: "#1f2937", halo: "#ffffff", grid: "rgba(31,41,55,0.28)" };

export function WindLegend() {
  return (
    <ul className="flex flex-wrap gap-x-2.5 gap-y-1 text-[10px] text-muted" aria-label="Wind speed bins in metres per second">
      {WIND_BIN_LABELS.map((l, i) => (
        <li key={l} className="flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: WIND_COLOURS[i] }} />
          {l} m/s
        </li>
      ))}
    </ul>
  );
}

export function SunLegend() {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted" aria-label="Sun path legend">
      {SUN_DAYS.map((d) => (
        <li key={d.id} className="flex items-center gap-1">
          <span className="h-0.5 w-4 rounded" style={{ background: SUN_COLOURS[d.id] }} />
          {d.label}
        </li>
      ))}
    </ul>
  );
}

/** Standalone responsive SVGs for the climate panel. */
export function SunPathChart({ lat, lon, offsetH, nowSun }: { lat: number; lon: number; offsetH: number; nowSun: { azimuth: number; altitude: number } | null }) {
  const k = 1.4; // rough on-screen scale for text sizing (viewBox 280 wide / 200 units)
  return (
    <svg viewBox="-130 -125 260 250" className="mx-auto block w-full max-w-[300px]" role="img" aria-label="Sun path diagram: stereographic projection with solstice and equinox arcs, north at top">
      <title>Sun path (stereographic), arcs for 21 Jun, equinox and 21 Dec; dots mark whole hours of local standard time</title>
      <SunPathLayer lat={lat} lon={lon} offsetH={offsetH} scale={k} ink={PANEL_INK} nowSun={nowSun} />
    </svg>
  );
}

export function WindRoseChart({ rose }: { rose: WindRose }) {
  return (
    <svg viewBox="-130 -125 260 250" className="mx-auto block w-full max-w-[300px]" role="img" aria-label="Wind rose: share of hours by direction the wind comes from and speed">
      <title>Wind rose</title>
      <WindRoseLayer rose={rose} scale={1.4} ink={PANEL_INK} />
    </svg>
  );
}
