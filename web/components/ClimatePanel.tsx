"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  comfortCounts,
  compassLabel,
  dayLabel,
  DAYS_IN_MONTH,
  MONTH_NAMES,
  MONTH_START_HOUR,
  TEMP_DOMAIN,
  TEMP_STOP_LIST,
  tempColour,
  typicalYearLabel,
  windRose,
} from "@/lib/climate";
import { num } from "@/lib/format";
import { approxOffsetH, sunPosition } from "@/lib/sunpath";
import type { Climate } from "@/lib/types";
import { Card, Stat } from "./Cards";
import { SunLegend, SunPathChart, WindLegend, WindRoseChart } from "./charts/SkyCharts";

const AXIS = "var(--graphite)";
const GRID = "var(--rule)";
/** One chart height for every monthly chart, and a 12-unit axis font: 1 unit is about 1 px at panel width. */
const CHART_H = 140;
const AXIS_FS = 12;

function Section({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <section className="space-y-1.5">
      <h4 className="text-sm font-semibold">{title}</h4>
      {children}
      {note && <p className="text-xs text-graphite">{note}</p>}
    </section>
  );
}

export function ClimateSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading climate data">
      <div className="grid grid-cols-3 gap-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="space-y-1.5">
            <div className="skeleton h-3 w-12" />
            <div className="skeleton h-5 w-16" />
          </div>
        ))}
      </div>
      <div className="skeleton h-40 w-full" />
      <div className="skeleton h-24 w-full" />
      <div className="skeleton h-32 w-full" />
    </div>
  );
}

// ---------- heatmap ----------
function Heatmap({ temps }: { temps: (number | null)[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [cur, setCur] = useState<{ day: number; hour: number } | null>(null);

  useEffect(() => {
    const c = canvas.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    for (let d = 0; d < 365; d++)
      for (let h = 0; h < 24; h++) {
        ctx.fillStyle = tempColour(temps[d * 24 + h]);
        ctx.fillRect(d, h, 1, 1);
      }
  }, [temps]);

  const pick = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const day = Math.min(364, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * 365)));
    const hour = Math.min(23, Math.max(0, Math.floor(((e.clientY - r.top) / r.height) * 24)));
    setCur({ day, hour });
  };
  const key = (e: React.KeyboardEvent) => {
    const step: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1], PageUp: [-7, 0], PageDown: [7, 0] };
    const s = step[e.key];
    if (!s) return;
    e.preventDefault();
    setCur((c) => {
      const b = c ?? { day: 0, hour: 12 };
      return { day: Math.min(364, Math.max(0, b.day + s[0])), hour: Math.min(23, Math.max(0, b.hour + s[1])) };
    });
  };
  const t = cur ? temps[cur.day * 24 + cur.hour] : null;
  const readout = cur ? `${dayLabel(cur.day)}, ${String(cur.hour).padStart(2, "0")}:00 to ${String(cur.hour + 1).padStart(2, "0")}:00: ${num(t, 1)} °C` : "Hover or use arrow keys to read a value";
  const lo = TEMP_DOMAIN[0];
  const hi = TEMP_DOMAIN[1];
  const grad = TEMP_STOP_LIST.map(([v, c]) => `${c} ${(((v - lo) / (hi - lo)) * 100).toFixed(1)}%`).join(",");

  return (
    <div>
      <div className="mb-1 h-4 text-xs nums" aria-live="polite">{readout}</div>
      <div className="flex gap-1.5">
        <div className="flex w-5 flex-col justify-between text-[11px] leading-none text-graphite" aria-hidden="true">
          {[0, 6, 12, 18].map((h) => <span key={h}>{String(h).padStart(2, "0")}</span>)}
          <span className="opacity-0">24</span>
        </div>
        <div
          className="relative flex-1 cursor-crosshair touch-none overflow-hidden"
          style={{ height: CHART_H - PAD.t - PAD.b }}
          tabIndex={0}
          role="img"
          aria-label="Annual hourly dry-bulb temperature heatmap: 365 days across, 24 hours down. Use arrow keys to inspect values."
          onPointerMove={pick}
          onPointerDown={pick}
          onPointerLeave={() => setCur(null)}
          onKeyDown={key}
        >
          <canvas ref={canvas} width={365} height={24} className="h-full w-full" style={{ imageRendering: "pixelated" }} />
          {cur && (
            <div
              className="pointer-events-none absolute border border-white shadow-[0_0_0_1px_rgba(0,0,0,0.7)]"
              style={{ left: `${(cur.day / 365) * 100}%`, top: `${(cur.hour / 24) * 100}%`, width: `${100 / 365}%`, minWidth: 3, height: `${100 / 24}%` }}
            />
          )}
        </div>
      </div>
      <div className="relative ml-[26px] mt-1 h-4 text-[11px] text-graphite" aria-hidden="true">
        {MONTH_NAMES.map((m, i) => (
          <span key={m} className="absolute" style={{ left: `${(MONTH_START_HOUR[i] / 8760) * 100}%` }}>{m[0]}</span>
        ))}
      </div>
      <div className="mt-1 flex items-center gap-2" aria-label="Temperature colour scale in degrees Celsius">
        <div className="ml-[26px] h-2 flex-1" style={{ background: `linear-gradient(90deg,${grad})` }} />
      </div>
      <div className="relative ml-[26px] mt-0.5 h-4 text-[11px] text-graphite nums" aria-hidden="true">
        {[-10, 0, 10, 20, 30, 40].map((v) => (
          <span key={v} className="absolute -translate-x-1/2" style={{ left: `${((v - lo) / (hi - lo)) * 100}%` }}>{v}°</span>
        ))}
      </div>
    </div>
  );
}

// ---------- shared monthly axes ----------
const W = 368;
const PAD = { l: 36, r: 8, t: 8, b: 20 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

function MonthAxis({ h }: { h: number }) {
  const bw = (W - PAD.l - PAD.r) / 12;
  return (
    <>
      {MONTH_NAMES.map((m, i) => (
        <text key={m} x={PAD.l + bw * (i + 0.5)} y={h - 4} fontSize={AXIS_FS} textAnchor="middle" fill={AXIS}>{m[0]}</text>
      ))}
    </>
  );
}

function MonthlyBars({ values, color, unit, label, digits = 0, h = CHART_H }: { values: (number | null)[]; color: string; unit: string; label: string; digits?: number; h?: number }) {
  const [hov, setHov] = useState<number | null>(null);
  const max = niceMax(Math.max(0, ...values.map((v) => v ?? 0)));
  const bw = (W - PAD.l - PAD.r) / 12;
  const y = (v: number) => PAD.t + (1 - v / max) * (h - PAD.t - PAD.b);
  const ticks = [0, max / 2, max];
  return (
    <div>
      <div className="h-4 text-xs nums" aria-live="polite">
        {hov !== null ? `${MONTH_NAMES[hov]}: ${num(values[hov], digits)} ${unit}` : ""}
      </div>
      <svg viewBox={`0 0 ${W} ${h}`} className="block w-full" role="img" aria-label={`${label}, monthly bars. ${values.map((v, i) => `${MONTH_NAMES[i]} ${num(v, digits)}`).join(", ")} ${unit}`} onPointerLeave={() => setHov(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={t === 0 ? 1 : 0.75} />
            <text x={PAD.l - 4} y={y(t) + 3} fontSize={AXIS_FS} textAnchor="end" fill={AXIS}>{Number.isInteger(t) ? t : t.toFixed(1)}</text>
          </g>
        ))}
        {values.map((v, i) => {
          if (v === null) return null;
          const top = y(v);
          const x = PAD.l + bw * i + 1.5;
          const w = bw - 3;
          const hgt = Math.max(0, y(0) - top);
          const r = Math.min(3, w / 2, hgt);
          return (
            <path key={i} d={`M${x} ${y(0)}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + w - r}Q${x + w} ${top} ${x + w} ${top + r}V${y(0)}Z`} fill={color} opacity={hov === null || hov === i ? 1 : 0.5} />
          );
        })}
        {values.map((_, i) => (
          <rect key={i} x={PAD.l + bw * i} y={PAD.t} width={bw} height={h - PAD.t - PAD.b} fill="transparent" onPointerEnter={() => setHov(i)} onPointerDown={() => setHov(i)} />
        ))}
        <MonthAxis h={h} />
      </svg>
    </div>
  );
}

// ---------- temperatures ----------
const T_BAND = "var(--ch-warm)";
function MonthlyTemps({ monthly }: { monthly: Climate["monthly"] }) {
  const [hov, setHov] = useState<number | null>(null);
  const h = CHART_H;
  const all = monthly.flatMap((m) => [m.temp_record_max_c, m.temp_record_min_c, m.temp_mean_daily_max_c, m.temp_mean_daily_min_c]).filter((v): v is number => typeof v === "number");
  const lo = Math.floor((Math.min(0, ...all) - 1) / 5) * 5;
  const hi = Math.ceil((Math.max(...all, 10) + 1) / 5) * 5;
  const bw = (W - PAD.l - PAD.r) / 12;
  const x = (i: number) => PAD.l + bw * (i + 0.5);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (h - PAD.t - PAD.b);
  const ticks: number[] = [];
  for (let t = lo; t <= hi; t += 10) ticks.push(t);
  const ok = (m: Climate["monthly"][number]) => typeof m.temp_mean_daily_max_c === "number" && typeof m.temp_mean_daily_min_c === "number";
  const upper = monthly.map((m, i) => (ok(m) ? `${x(i)} ${y(m.temp_mean_daily_max_c!)}` : null)).filter(Boolean);
  const lower = monthly.map((m, i) => (ok(m) ? `${x(i)} ${y(m.temp_mean_daily_min_c!)}` : null)).filter(Boolean).reverse();
  const band = upper.length ? `M${upper.join("L")}L${lower.join("L")}Z` : "";
  const mean = monthly.map((m, i) => (typeof m.temp_mean_c === "number" ? `${x(i)} ${y(m.temp_mean_c)}` : null)).filter(Boolean);
  const m = hov !== null ? monthly[hov] : null;
  return (
    <div>
      <div className="h-4 text-xs nums" aria-live="polite">
        {m ? `${MONTH_NAMES[hov!]}: mean ${num(m.temp_mean_c)}, daily ${num(m.temp_mean_daily_min_c)} to ${num(m.temp_mean_daily_max_c)}, record ${num(m.temp_record_min_c)} / ${num(m.temp_record_max_c)} °C` : ""}
      </div>
      <svg viewBox={`0 0 ${W} ${h}`} className="block w-full" role="img" aria-label={`Monthly temperatures. ${monthly.map((q, i) => `${MONTH_NAMES[i]} mean ${num(q.temp_mean_c)}`).join(", ")} °C`} onPointerLeave={() => setHov(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={t === 0 ? 1.25 : 0.75} />
            <text x={PAD.l - 4} y={y(t) + 3} fontSize={AXIS_FS} textAnchor="end" fill={AXIS}>{t}°</text>
          </g>
        ))}
        {band && <path d={band} fill={T_BAND} opacity={0.28} />}
        {mean.length > 0 && <path d={`M${mean.join("L")}`} fill="none" stroke={T_BAND} strokeWidth={2} />}
        {monthly.map((q, i) => (
          <g key={i} stroke="var(--sheet)" strokeWidth={2}>
            {typeof q.temp_record_max_c === "number" && <circle cx={x(i)} cy={y(q.temp_record_max_c)} r={3} fill="var(--ch-warm)" />}
            {typeof q.temp_record_min_c === "number" && <circle cx={x(i)} cy={y(q.temp_record_min_c)} r={3} fill="var(--ch-cool)" />}
          </g>
        ))}
        {hov !== null && <line x1={x(hov)} x2={x(hov)} y1={PAD.t} y2={h - PAD.b} stroke={AXIS} strokeWidth={0.75} strokeDasharray="2 2" />}
        {monthly.map((_, i) => (
          <rect key={i} x={PAD.l + bw * i} y={PAD.t} width={bw} height={h - PAD.t - PAD.b} fill="transparent" onPointerEnter={() => setHov(i)} onPointerDown={() => setHov(i)} />
        ))}
        <MonthAxis h={h} />
      </svg>
      <ul className="flex flex-nowrap gap-x-3 text-[11px] text-graphite" aria-label="Legend">
        <li className="flex items-center gap-1 whitespace-nowrap"><span className="h-2.5 w-3.5 opacity-40" style={{ background: T_BAND }} />Daily range</li>
        <li className="flex items-center gap-1 whitespace-nowrap"><span className="h-0.5 w-3.5" style={{ background: T_BAND }} />Mean</li>
        <li className="flex items-center gap-1 whitespace-nowrap"><span className="h-2 w-2 rounded-full" style={{ background: "var(--ch-warm)" }} />Record high</li>
        <li className="flex items-center gap-1 whitespace-nowrap"><span className="h-2 w-2 rounded-full" style={{ background: "var(--ch-cool)" }} />Record low</li>
      </ul>
    </div>
  );
}

// ---------- comfort ----------
const COMFORT = [
  { key: "cold", label: "Below 18 °C", color: "var(--ch-cool)" },
  { key: "comfortable", label: "18 to 26 °C", color: "var(--ch-ok)" },
  { key: "hot", label: "Above 26 °C", color: "var(--ch-warm)" },
] as const;

function Comfort({ temps }: { temps: (number | null)[] }) {
  const [hov, setHov] = useState<number | null>(null);
  const data = useMemo(() => comfortCounts(temps), [temps]);
  const h = CHART_H;
  const bw = (W - PAD.l - PAD.r) / 12;
  const y = (pctv: number) => PAD.t + (1 - pctv) * (h - PAD.t - PAD.b);
  const annual = data.reduce((a, m) => a + m.comfortable, 0);
  return (
    <div>
      <div className="h-4 text-xs nums" aria-live="polite">
        {hov !== null
          ? `${MONTH_NAMES[hov]}: ${data[hov].cold} h cold, ${data[hov].comfortable} h comfortable, ${data[hov].hot} h hot`
          : `${annual.toLocaleString()} comfortable hours a year (${((annual / 8760) * 100).toFixed(0)} %)`}
      </div>
      <svg viewBox={`0 0 ${W} ${h}`} className="block w-full" role="img" aria-label={`Comfort hours per month. ${data.map((m, i) => `${MONTH_NAMES[i]}: ${m.comfortable} comfortable of ${DAYS_IN_MONTH[i] * 24}`).join(", ")}`} onPointerLeave={() => setHov(null)}>
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={0.75} />
            <text x={PAD.l - 4} y={y(t) + 3} fontSize={AXIS_FS} textAnchor="end" fill={AXIS}>{t * 100}%</text>
          </g>
        ))}
        {data.map((m, i) => {
          const total = DAYS_IN_MONTH[i] * 24;
          let acc = 0;
          return (
            <g key={i} opacity={hov === null || hov === i ? 1 : 0.55}>
              {COMFORT.map((c) => {
                const v = m[c.key] / total;
                const y0 = y(acc);
                acc += v;
                const y1 = y(acc);
                if (v <= 0) return null;
                return <rect key={c.key} x={PAD.l + bw * i + 1.5} width={bw - 3} y={y1} height={Math.max(0, y0 - y1 - (v < 1 ? 1 : 0))} fill={c.color} />;
              })}
            </g>
          );
        })}
        {data.map((_, i) => (
          <rect key={i} x={PAD.l + bw * i} y={PAD.t} width={bw} height={h - PAD.t - PAD.b} fill="transparent" onPointerEnter={() => setHov(i)} onPointerDown={() => setHov(i)} />
        ))}
        <MonthAxis h={h} />
      </svg>
      <ul className="flex flex-nowrap gap-x-3 text-[11px] text-graphite nums" aria-label="Legend">
        {COMFORT.map((c) => (
          <li key={c.key} className="flex items-center gap-1 whitespace-nowrap"><span className="h-2.5 w-2.5" style={{ background: c.color }} />{c.label}</li>
        ))}
      </ul>
    </div>
  );
}

// ---------- panel ----------
export function ClimatePanel({
  climate,
  loading,
  error,
  onRetry,
  windMonth,
  onWindMonth,
  lat,
  lon,
  onDownloadEpw,
  epwBusy,
}: {
  climate: Climate | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  windMonth: number | null;
  onWindMonth: (m: number | null) => void;
  lat: number;
  lon: number;
  onDownloadEpw: () => void;
  epwBusy: boolean;
}) {
  const hourly = climate?.typical_year.hourly;
  const rose = useMemo(() => (hourly ? windRose(hourly.wind_speed_ms, hourly.wind_direction_deg, windMonth) : null), [hourly, windMonth]);
  const annualRose = useMemo(() => (hourly ? windRose(hourly.wind_speed_ms, hourly.wind_direction_deg, null) : null), [hourly]);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (error && !climate)
    return (
      <Card title="Climate">
        <p className="text-xs">Climate data failed to load: {error}</p>
        <button onClick={onRetry} className="mt-2 border border-edge px-3 py-1.5 text-xs font-semibold hover:bg-hover">Retry</button>
      </Card>
    );
  if (!climate || !hourly || !rose || !annualRose)
    return (
      <Card title="Climate" loading={loading}>
        {loading ? <ClimateSkeleton /> : <p className="text-xs text-graphite">Climate data appears once site data has loaded.</p>}
      </Card>
    );

  const a = climate.annual;
  const offset = climate.timezone.standard_offset_h ?? approxOffsetH(lon);
  const nowSun = sunPosition(now, lat, lon);
  const src = climate.source;
  const tz = climate.timezone;
  return (
    <div className="space-y-6">
      <Card title="Climate summary">
        <div className="grid grid-cols-3 gap-x-3 gap-y-2.5">
          <Stat label="Mean temp" value={num(a.mean_temp_c)} unit="°C" />
          <Stat label="Heating degree days" value={num(a.hdd_18c, 0)} title="Base 18 °C" />
          <Stat label="Cooling degree days" value={num(a.cdd_18c, 0)} title="Base 18 °C" />
          <Stat label="Solar (GHI)" value={num(a.ghi_kwh_m2, 0)} unit="kWh/m²" />
          <Stat label="Precipitation" value={num(a.precip_mm, 0)} unit="mm" />
          <Stat label="Prevailing wind" value={compassLabel(annualRose.prevailing)} unit={annualRose.meanSpeed !== null ? `${num(annualRose.meanSpeed)} m/s` : undefined} title="Direction the wind blows from, with annual mean speed" />
        </div>
      </Card>

      <Card title="Wind rose" major>
        <div className="mb-2 flex items-center gap-2 text-xs">
          <label htmlFor="wind-month" className="text-graphite">Period</label>
          <select
            id="wind-month"
            value={windMonth === null ? "all" : String(windMonth)}
            onChange={(e) => onWindMonth(e.target.value === "all" ? null : Number(e.target.value))}
            className="border border-rule bg-sheet px-2 py-1 text-xs"
          >
            <option value="all">Annual</option>
            {MONTH_NAMES.map((m, i) => <option key={m} value={i}>{m}</option>)}
          </select>
          <span className="ml-auto text-xs text-graphite">
            Also drives the map overlay
          </span>
        </div>
        <WindRoseChart rose={rose} />
        <div className="mt-1"><WindLegend /></div>
        <p className="mt-1 text-xs text-graphite">Petals point to where the wind comes from; length is share of hours. Prevailing: {compassLabel(rose.prevailing)}, mean {num(rose.meanSpeed)} m/s.</p>
      </Card>

      <Card title="Temperature" major>
        <div className="space-y-5">
          <Section title="Hourly dry-bulb temperature, typical year">
            <Heatmap temps={hourly.temperature_c} />
          </Section>
          <Section title="Monthly temperature (°C)">
            <MonthlyTemps monthly={climate.monthly} />
          </Section>
          <Section title="Precipitation (mm)">
            <MonthlyBars values={climate.monthly.map((m) => m.precip_mm)} color="var(--ch-rain)" unit="mm" label="Monthly precipitation" />
          </Section>
        </div>
      </Card>

      <Card title="Solar" major>
        <div className="space-y-5">
          <Section title="Global horizontal irradiation (kWh/m²)">
            <MonthlyBars values={climate.monthly.map((m) => m.ghi_kwh_m2)} color="var(--ch-solar)" unit="kWh/m²" label="Monthly global horizontal irradiation" />
          </Section>
          <Section title="Sun path" note={`Stereographic, north at top. Hour dots in local standard time (UTC${offset >= 0 ? "+" : ""}${offset}${tz.approximate ? ", approximate" : ""}). The filled marker is the sun now.`}>
            <SunPathChart lat={lat} lon={lon} offsetH={offset} nowSun={nowSun} />
            <SunLegend />
          </Section>
        </div>
      </Card>

      <Card title="Thermal comfort" major>
        <Comfort temps={hourly.temperature_c} />
        <p className="mt-1 text-xs text-graphite">Hours by dry-bulb temperature only, from the typical-year hourly data. Not an adaptive comfort or PMV model.</p>
      </Card>

      <Card title="EnergyPlus weather file">
        <button
          onClick={onDownloadEpw}
          disabled={epwBusy}
          className="w-full border border-edge px-3 py-2 text-sm font-semibold transition-opacity hover:bg-hover disabled:opacity-40"
        >
          {epwBusy ? "Building EPW" : "Download EPW for Ladybug and EnergyPlus"}
        </button>
        <p className="mt-1 text-xs text-graphite">A zip containing a typical-year .epw for this site.</p>
      </Card>

      <p className="pb-2 text-xs leading-relaxed text-graphite">
        <strong>Regional climate, not site microclimate.</strong> {src.name}, {src.period}; grid point {src.grid_point_lonlat[1].toFixed(2)}, {src.grid_point_lonlat[0].toFixed(2)}
        {typeof src.elevation_m === "number" ? ` at ${Math.round(src.elevation_m)} m` : ""}. {src.licence}. {src.note}
        {" "}Typical year built from: {typicalYearLabel(climate.typical_year.months_from_years)}. {climate.typical_year.method}
        {tz.name ? ` Time zone ${tz.name}.` : ""}
      </p>
    </div>
  );
}
