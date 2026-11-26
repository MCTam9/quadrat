"use client";

import { Logo } from "./Logo";
import { useRef, useState, type ComponentProps, type PointerEvent as ReactPointerEvent } from "react";
import type { HeightShares } from "@/lib/buildings";
import { num } from "@/lib/format";
import { areaKm2, type SquareState } from "@/lib/square";
import { formatCoords, type SiteName } from "@/lib/site-name";
import type { Analysis, LayerEvent, Preview } from "@/lib/types";
import { AccessCard, ClimateCard, ConstraintsCard, DensityMore, LandUseCard, StreetsCard, TerrainCard } from "./Cards";
import { ClimatePanel } from "./ClimatePanel";
import { ExportPanel, type ExportRequest } from "./ExportPanel";
import { CompletenessLine, Schedule } from "./Schedule";
import { SquareControls, SunTimes } from "./SquareCard";

export type Tab = "analysis" | "climate";

interface Props {
  square: SquareState | null;
  onSquare: (s: SquareState) => void;
  name: SiteName | null;
  analysis: Analysis | null;
  preview: Preview | null;
  shares: HeightShares | null;
  typeKnown: number | null;
  stale: boolean;
  loading: boolean;
  loadList: LayerEvent[];
  tab: Tab;
  onTab: (t: Tab) => void;
  climate: ComponentProps<typeof ClimatePanel>;
  exporting: boolean;
  canExport: boolean;
  onExport: (r: ExportRequest) => void;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "analysis", label: "Analysis" },
  { id: "climate", label: "Climate" },
];

/** The drawing title block: site name, key figures, then the analysis, with the download pinned as its footer.
 *  On a phone it starts as a peek bar and expands on tap or drag. */
export function SitePanel(p: Props) {
  const [open, setOpen] = useState(false);
  const drag = useRef<number | null>(null);
  const swiped = useRef(false);
  const m = p.analysis?.metrics;
  const sq = p.square;
  const title = sq ? (p.name?.title ?? formatCoords(sq.lat, sq.lon)) : "Pick a site";

  // A swipe up or down opens or closes the sheet; a tap (the click event) toggles it.
  const down = (e: ReactPointerEvent) => {
    drag.current = e.clientY;
    swiped.current = false;
  };
  const up = (e: ReactPointerEvent) => {
    const y = drag.current;
    drag.current = null;
    if (y == null || Math.abs(e.clientY - y) <= 24) return;
    swiped.current = true;
    setOpen(e.clientY < y);
  };
  const tap = () => {
    if (swiped.current) swiped.current = false;
    else setOpen((o) => !o);
  };

  const onTabKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = p.tab === "analysis" ? "climate" : "analysis";
    p.onTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  };

  return (
    <aside
      className={`sheet absolute inset-x-0 bottom-0 z-20 flex flex-col overflow-hidden transition-[height] max-sm:border-x-0 max-sm:border-b-0 sm:inset-x-auto sm:bottom-3 sm:right-3 sm:top-3 sm:w-[25rem] ${open ? "max-sm:h-[76dvh]" : "max-sm:h-(--peek)"}`}
      aria-label="Site analysis"
    >
      {/* phone: peek bar, tap or drag to expand */}
      <button
        type="button"
        className="flex h-(--peek) shrink-0 touch-none flex-col justify-center gap-1 px-4 text-left sm:hidden"
        aria-expanded={open}
        aria-controls="site-panel-body"
        onPointerDown={down}
        onPointerUp={up}
        onPointerCancel={() => (drag.current = null)}
        onClick={tap}
      >
        <span className="mx-auto -mt-1 h-1 w-10 bg-rule" aria-hidden />
        <span className="flex items-baseline gap-3">
          <span className="wide min-w-0 flex-1 truncate text-lg font-bold">{title}</span>
          {sq && (
            <span className="wide shrink-0 text-sm font-semibold">
              <span className="text-graphite">FSI </span>
              {num(m?.fabric?.fsi, 2)}
              <span className="ml-3 text-graphite">{areaKm2(sq).toFixed(2)} km²</span>
            </span>
          )}
        </span>
      </button>

      <div id="site-panel-body" className="flex min-h-0 flex-1 flex-col">
        {!sq ? (
          <div className="p-4 text-sm leading-relaxed text-graphite">
            <p className="wide flex items-center gap-2.5 text-2xl font-bold text-ink">
              <Logo size={30} />
              Quadrat
            </p>
            <p className="mb-2 mt-3 font-semibold text-ink">Pick a site</p>
            Search for a place, or click the map to drop a square. Drag its centre to move it; drag a corner or the red line to resize.
            Live analysis and a building preview appear before you download anything.
          </div>
        ) : (
          <>
            <header className="shrink-0 space-y-3 border-b border-edge p-4 max-sm:pt-1">
              <div className="max-sm:hidden">
                <div className="min-w-0">
                  <h1 className="wide text-2xl font-bold leading-tight">{title}</h1>
                  {p.name?.place && <p className="mt-0.5 text-sm text-graphite">{p.name.place}</p>}
                </div>
              </div>
              <SquareControls square={sq} onChange={p.onSquare} />
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="p-4 pb-2">
                <Schedule square={sq} m={m?.fabric} shares={p.shares} loading={p.stale} />
                <CompletenessLine a={p.analysis} shares={p.shares} typeKnown={p.typeKnown} />
              </div>

              <div className="sticky top-0 z-10 flex gap-5 bg-sheet px-4" role="tablist" aria-label="Panel" onKeyDown={onTabKey}>
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    id={`tab-${t.id}`}
                    role="tab"
                    aria-selected={p.tab === t.id}
                    aria-controls={`panel-${t.id}`}
                    tabIndex={p.tab === t.id ? 0 : -1}
                    onClick={() => p.onTab(t.id)}
                    className={`-mb-px border-b-2 py-2 text-sm font-semibold ${p.tab === t.id ? "border-ink" : "border-transparent text-graphite hover:text-ink"}`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div id={`panel-${p.tab}`} role="tabpanel" aria-labelledby={`tab-${p.tab}`} className="space-y-6 p-4">
                {p.tab === "climate" ? (
                  <ClimatePanel {...p.climate} />
                ) : (
                  <>
                    {p.loading && (
                      <section aria-live="polite">
                        <h3 className="mb-2 text-sm font-semibold">Loading site data</h3>
                        <ul className="space-y-1 text-xs">
                          {p.loadList.map((l) => (
                            <li key={l.layer} className="flex items-center gap-2">
                              <span className="w-3 text-center" aria-label={l.ok ? "loaded" : "failed"}>{l.ok ? "✓" : "✕"}</span>
                              <span className="capitalize">{l.layer}</span>
                              <span className="ml-auto text-graphite nums">
                                {l.provider ?? ""}
                                {typeof l.features === "number" ? `, ${l.features}` : ""}
                              </span>
                            </li>
                          ))}
                          <li className="flex items-center gap-2 text-graphite"><span className="skeleton h-3 w-3" />Fetching</li>
                        </ul>
                      </section>
                    )}
                    <LandUseCard m={m?.landuse} loading={p.stale} stale={p.stale && !!m} />
                    <StreetsCard m={m?.street} loading={p.stale} stale={p.stale && !!m} />
                    <ConstraintsCard fc={p.preview?.constraints} />
                    <TerrainCard m={m?.terrain} loading={p.stale} stale={p.stale && !!m} />
                    <AccessCard m={m?.access} loading={p.stale} stale={p.stale && !!m} />
                    <ClimateCard m={m?.climate} loading={p.stale} stale={p.stale && !!m} />
                    <DensityMore m={m?.fabric} />
                    <SunTimes square={sq} />
                  </>
                )}
              </div>
            </div>

            <ExportPanel busy={p.exporting} disabled={!p.canExport} onExport={p.onExport} />
          </>
        )}
      </div>
    </aside>
  );
}

