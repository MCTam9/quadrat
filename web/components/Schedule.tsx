"use client";

import { useId, useState } from "react";
import { knownShare, type HeightShares } from "@/lib/buildings";
import { asNum, num, pct } from "@/lib/format";
import { areaKm2, type SquareState } from "@/lib/square";
import type { Analysis, Metrics } from "@/lib/types";
import { HEIGHT_SOURCE } from "@/lib/vocab.generated";

const SHORT: Record<string, string> = { height: "height tag", lidar: "LiDAR", levels: "storeys", tiles: "map tiles", unknown: "none" };

/** How the building heights behind FSI were found, e.g. "height tag 20 %, LiDAR 50 %". */
export function heightSourceText(s: HeightShares): string {
  return HEIGHT_SOURCE.filter((h) => s[h.id] > 0.004)
    .map((h) => `${SHORT[h.id]} ${pct(s[h.id])}`)
    .join(", ");
}

function densityWarning(m: Metrics | undefined, known: number | null): string | null {
  if (!m) return null;
  if (m.fsi == null) return "FSI not computed: too few building heights are known for this site.";
  if (known != null && known < 0.4)
    return `Only ${Math.round(known * 100)} % of building heights are known, so FSI uses a satellite average height (100 m cells) and is an estimate.`;
  if (known != null && known < 0.8) return `${Math.round((1 - known) * 100)} % of buildings have no height and count as zero floors in FSI.`;
  return null;
}

/** A thin meter whose empty part is the missing-data hatch, as on the map. */
function Bar({ value, className = "" }: { value: number; className?: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <span className={`missing-hatch relative inline-block h-1.5 overflow-hidden border border-rule align-middle ${className}`} aria-hidden>
      <span className="absolute inset-y-0 left-0 bg-ink" style={{ width: `${v * 100}%` }} />
    </span>
  );
}

/**
 * A term with a definition that pops up on hover or keyboard focus, and toggles on tap for
 * touch screens. Dotted underline marks it as explained.
 */
export function Term({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-block" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="cursor-help underline decoration-dotted decoration-1 underline-offset-4"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        {label}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="sheet absolute left-0 top-full z-30 mt-1.5 block w-72 space-y-1.5 p-3 text-left text-xs font-normal leading-snug text-ink shadow-[0_2px_8px_rgba(0,0,0,0.12)]"
        >
          {children}
        </span>
      )}
    </span>
  );
}

const TYPICAL = "text-graphite";

function FsiTip({ fsi, gsi }: { fsi: number | null; gsi: number | null }) {
  const storeys = fsi != null && gsi ? fsi / gsi : null;
  return (
    <>
      <span className="block font-semibold">Floor space index</span>
      <span className="block">
        Total floor area across all storeys, divided by the site area.
        {fsi != null && ` ${num(fsi, 2)} means ${num(fsi, 2)} m² of floor for every m² of ground.`}
      </span>
      <span className="block">Floor area is footprint × height ÷ 3 m per storey. Buildings with no known height count as zero floors.</span>
      {storeys != null && <span className="block">FSI ÷ GSI ≈ {num(storeys, 1)} storeys on average.</span>}
      <span className={`block ${TYPICAL}`}>Also called floor area ratio (FAR) or plot ratio. Suburb 0.3–0.5, terraces 1–1.5, central London 3–4, City of London 5+.</span>
    </>
  );
}

function GsiTip({ gsi }: { gsi: number | null }) {
  return (
    <>
      <span className="block font-semibold">Ground space index</span>
      <span className="block">
        Building footprints divided by the site area.
        {gsi != null && ` ${num(gsi, 2)} means buildings cover ${Math.round(gsi * 100)} % of the ground; the rest is streets, yards and open space.`}
      </span>
      <span className={`block ${TYPICAL}`}>Also called site coverage. Suburb 0.15–0.25, terraces 0.4–0.5, dense centres 0.5–0.6.</span>
    </>
  );
}

function Row({ label, children, aside }: { label: React.ReactNode; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[4.5rem_1fr_auto] items-baseline gap-x-3 border-t border-rule py-2 last:border-b">
      <dt className="text-sm text-graphite">{label}</dt>
      <dd className="wide text-2xl font-semibold leading-none">{children}</dd>
      <dd className="text-right text-xs text-graphite">{aside}</dd>
    </div>
  );
}

/** The key figures, as a ruled schedule. Completeness sits next to the figure it qualifies. */
export function Schedule({
  square,
  m,
  shares,
  loading,
}: {
  square: SquareState;
  m?: Metrics;
  shares: HeightShares | null;
  loading: boolean;
}) {
  const known = shares ? knownShare(shares) : asNum(m?.fsi_coverage);
  const warn = densityWarning(m, known);
  const wait = !m;
  const val = (v: React.ReactNode) => (wait ? <span className="skeleton inline-block h-6 w-16 align-middle" aria-label="Loading" /> : v);
  return (
    <div className={loading && m ? "opacity-60 transition-opacity" : "transition-opacity"} aria-busy={loading}>
      <h3 className="sr-only">Key figures</h3>
      <dl>
        <Row
          label={
            <Term label="FSI">
              <FsiTip fsi={asNum(m?.fsi) ?? null} gsi={asNum(m?.gsi) ?? null} />
            </Term>
          }
          aside={
            known != null && !wait ? (
              <span className="inline-flex items-center gap-1.5" title={shares ? heightSourceText(shares) : undefined}>
                <Bar value={known} className="w-12" />
                <span className="nums">{pct(known)} of heights known</span>
              </span>
            ) : null
          }
        >
          {val(num(m?.fsi, 2))}
        </Row>
        <Row
          label={
            <Term label="GSI">
              <GsiTip gsi={asNum(m?.gsi) ?? null} />
            </Term>
          }
        >{val(num(m?.gsi, 2))}</Row>
        <Row label="Buildings">{val(asNum(m?.building_count) ?? "–")}</Row>
        <Row label="Area">
          {areaKm2(square).toFixed(2)} <span className="text-sm font-normal text-graphite">km²</span>
        </Row>
      </dl>
      {warn && !wait && (
        <p className="mt-2 flex gap-2 text-xs leading-snug text-graphite">
          <span className="missing-hatch mt-0.5 inline-block h-2.5 w-2.5 shrink-0 border border-rule" aria-hidden />
          {warn}
        </p>
      )}
    </div>
  );
}

function Meter({ label, value, note }: { label: string; value: number | null; note?: string }) {
  const v = value == null ? null : Math.max(0, Math.min(1, value));
  return (
    <li>
      <div className="flex items-baseline gap-2 text-xs">
        <span>{label}</span>
        <span className="ml-auto font-semibold nums">{v == null ? "n/a" : `${Math.round(v * 100)} %`}</span>
      </div>
      <div
        className="missing-hatch relative mt-1 h-1.5 overflow-hidden border border-rule"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={v == null ? undefined : Math.round(v * 100)}
      >
        {v != null && <div className="h-full bg-ink" style={{ width: `${v * 100}%` }} />}
      </div>
      {note && <p className="mt-0.5 text-xs leading-snug text-graphite">{note}</p>}
    </li>
  );
}

/** One compact line that expands into the full completeness breakdown. */
export function CompletenessLine({
  a,
  shares,
  typeKnown,
}: {
  a: Analysis | null;
  shares: HeightShares | null;
  typeKnown: number | null;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!a) return null;
  const L = a.layers ?? {};
  const fab = a.metrics?.fabric;
  const lu = a.metrics?.landuse;
  const heights = shares ? knownShare(shares) : (asNum(fab?.fsi_coverage) ?? asNum(L.buildings?.coverage));
  const unmapped = asNum(lu?.landuse_unmapped_fraction);
  const landMapped = unmapped == null ? null : 1 - unmapped;
  const warnings = a.assessment?.warnings ?? [];
  const errors = Object.entries(a.metrics?.errors ?? {});
  const terrainNote = L.terrain?.provider?.includes("copernicus")
    ? "Surface model (30 m): includes roofs and trees, so slopes read high in built-up areas."
    : undefined;
  const items: [string, number | null][] = [
    ["building heights", heights],
    ["building type", typeKnown],
    ["land use mapped", landMapped],
  ];
  const known = items.filter((i): i is [string, number] => i[1] != null);
  const worst = known.length ? known.reduce((a, b) => (b[1] < a[1] ? b : a)) : null;
  const thin = known.filter((i) => i[1] < 0.5).length;
  const pct = (v: number) => `${Math.round(v * 100)} %`;
  const summary = !worst
    ? ""
    : thin > 1
      ? `${thin} gaps, worst: ${worst[0]} ${pct(worst[1])}`
      : thin === 1
        ? `Gap: ${worst[0]} only ${pct(worst[1])}`
        : `All above half; lowest ${worst[0]} ${pct(worst[1])}`;
  const notes = [...(L.buildings?.notes ?? []), ...(L.landuse?.notes ?? [])];
  return (
    <div className="mt-2">
      <button
        type="button"
        className="flex w-full items-center gap-2 py-1.5 text-left text-xs"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="font-semibold">Data completeness</span>
        <span className="truncate text-graphite">{summary}</span>
        <svg className={`ml-auto h-3 w-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <path d="M2 4.5 6 8.5 10 4.5" />
        </svg>
      </button>
      {open && (
        <div id={id} className="space-y-3 pb-2 pt-1">
          <ul className="space-y-2.5">
            <Meter label="Building heights" value={heights} note={shares ? `By source: ${heightSourceText(shares)}.` : "From OSM height and storey tags."} />
            <Meter label="Building type" value={typeKnown} note="Tagged, or inferred from businesses inside or the land-use zone." />
            <Meter label="Land use mapped" value={landMapped} />
            {asNum(L.landcover?.coverage) != null && <Meter label="Land cover (satellite)" value={asNum(L.landcover?.coverage)} />}
            {asNum(L.terrain?.coverage) != null && <Meter label="Terrain" value={asNum(L.terrain?.coverage)} note={terrainNote} />}
          </ul>
          {typeof fab?.fsi_source === "string" && <p className="text-xs text-graphite">FSI basis: {fab.fsi_source}</p>}
          {(warnings.length > 0 || errors.length > 0 || notes.length > 0) && (
            <ul className="space-y-1 text-xs">
              {warnings.map((w, i) => (
                <li key={`w${i}`}>{w}</li>
              ))}
              {errors.map(([k, v]) => (
                <li key={k}>
                  {k}: {v}
                </li>
              ))}
              {notes.map((n, i) => (
                <li key={`n${i}`} className="text-graphite">
                  {n}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-graphite">Hatched is missing, on the map and here.</p>
        </div>
      )}
    </div>
  );
}
