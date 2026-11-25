"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { analyse, climate as fetchClimate, exportZip, loadSite, preview as fetchPreview, ReloadRequired, type SiteParams } from "@/lib/api";
import { useTokenGetter } from "@/lib/auth";
import { CLERK_ENABLED } from "@/lib/env";
import type { Map as MapLibreMap } from "maplibre-gl";
import {
  annotateBuildings,
  annotateConstraints,
  annotateContours,
  annotateStreets,
  DEFAULT_LAYERS,
  loadLayers,
  typeSourceShares,
  saveLayers,
  type LayerState,
} from "@/lib/layers";
import { clampHalf, moveCentre, withinPadded, type SquareState } from "@/lib/square";
import type { Analysis, Climate, LayerEvent, Preview, ReadyEvent } from "@/lib/types";
import { Search } from "./Search";
import { ClimatePanel } from "./ClimatePanel";
import { Legend, LayersControl } from "./LayersControl";
import { SkyOverlay } from "./SkyOverlay";
import { SquareCard } from "./SquareCard";
import { ExportPanel, type ExportRequest } from "./ExportPanel";
import { AccessCard, ClimateCard, CompletenessCard, ConstraintsCard, DensityCard, LandUseCard, StreetsCard, TerrainCard } from "./Cards";

const MapView = dynamic(() => import("./MapView"), { ssr: false });

const DEFAULT_HALF = 250;
const WORLD = { lon: 10, lat: 30, zoom: 1.6 };

interface Toast {
  id: number;
  msg: string;
}

export function Picker() {
  const getToken = useTokenGetter();
  const tokenRef = useRef(getToken);
  useEffect(() => {
    tokenRef.current = getToken;
  }, [getToken]);
  const tok = useCallback(() => tokenRef.current(), []);

  const [square, setSquare] = useState<SquareState | null>(null);
  const [settled, setSettled] = useState<SquareState | null>(null);
  const [loaded, setLoaded] = useState<ReadyEvent | null>(null);
  const [layers, setLayers] = useState<Record<string, LayerEvent>>({});
  const [loading, setLoading] = useState(false);
  const [analysing, setAnalysing] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [prev, setPrev] = useState<Preview | null>(null);
  const [threeD, setThreeD] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(true);
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; zoom?: number; nonce: number } | null>(null);
  const [initial, setInitial] = useState(WORLD);
  const [exporting, setExporting] = useState(false);
  const [layerState, setLayerState] = useState<LayerState>(DEFAULT_LAYERS);
  const [tab, setTab] = useState<"analysis" | "climate">("analysis");
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [climate, setClimate] = useState<Climate | null>(null);
  const [climateLoading, setClimateLoading] = useState(false);
  const [climateError, setClimateError] = useState<string | null>(null);
  const [climateNonce, setClimateNonce] = useState(0);
  const [windMonth, setWindMonth] = useState<number | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const ctl = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadedRef = useRef<ReadyEvent | null>(null);
  const loadedAt = useRef<{ lon: number; lat: number } | null>(null);

  const toast = useCallback((msg: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  // initial state from URL
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const lat = parseFloat(q.get("lat") ?? "");
    const lon = parseFloat(q.get("lon") ?? "");
    const size = parseFloat(q.get("size") ?? "");
    if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 85 && Math.abs(lon) <= 180) {
      const s = { lon, lat, halfWidthM: clampHalf(Number.isFinite(size) ? size / 2 : DEFAULT_HALF) };
      /* eslint-disable react-hooks/set-state-in-effect */
      setInitial({ lon, lat, zoom: 15 });
      setSquare(s);
      setSettled(s);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLayerState(loadLayers());
  }, []);
  const changeLayers = useCallback((l: LayerState) => {
    setLayerState(l);
    saveLayers(l);
  }, []);

  const cancelWork = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    ctl.current?.abort();
  }, []);

  const onSquare = useCallback(
    (s: SquareState, final: boolean) => {
      setSquare(s);
      if (final) setSettled(s);
      else cancelWork();
    },
    [cancelWork],
  );

  const place = useCallback((lon: number, lat: number) => {
    setSquare((cur) => {
      const s = cur ? moveCentre(cur, lon, lat) : { lon, lat, halfWidthM: DEFAULT_HALF };
      setSettled(s);
      return s;
    });
  }, []);

  const pick = useCallback(
    (lon: number, lat: number) => {
      place(lon, lat);
      setFlyTo({ lon, lat, zoom: 15, nonce: Date.now() });
    },
    [place],
  );

  const ensureLoaded = useCallback(
    async (s: SquareState, signal: AbortSignal, force = false): Promise<ReadyEvent> => {
      const cur = loadedRef.current;
      const at = loadedAt.current;
      if (!force && cur && at && withinPadded(s, { ...at, paddedHalfM: cur.padded_half_width_m })) return cur;
      setLoading(true);
      setLayers({});
      try {
        const ready = await loadSite(s.lon, s.lat, s.halfWidthM, tok, (l) => setLayers((m) => ({ ...m, [l.layer]: l })), signal);
        loadedRef.current = ready;
        loadedAt.current = { lon: ready.centre[0], lat: ready.centre[1] };
        setLoaded(ready);
        return ready;
      } finally {
        setLoading(false);
      }
    },
    [tok],
  );

  // run analysis once the square settles (debounced)
  useEffect(() => {
    if (!settled) return;
    const s = settled;
    const q = new URLSearchParams({ lat: s.lat.toFixed(6), lon: s.lon.toFixed(6), size: String(Math.round(s.halfWidthM * 2)) });
    window.history.replaceState(null, "", `?${q}`);

    timer.current = setTimeout(async () => {
      const c = new AbortController();
      ctl.current = c;
      try {
        const run = async (force: boolean) => {
          const ready = await ensureLoaded(s, c.signal, force);
          const p: SiteParams = { site_id: ready.site_id, lon: s.lon, lat: s.lat, half_width_m: s.halfWidthM };
          setAnalysing(true);
          const [a, pv] = await Promise.all([analyse(p, tok, c.signal), fetchPreview(p, tok, c.signal)]);
          setAnalysis(a);
          setPrev(pv);
        };
        try {
          await run(false);
        } catch (e) {
          if (e instanceof ReloadRequired) await run(true);
          else throw e;
        }
      } catch (e) {
        if ((e as Error).name !== "AbortError") toast((e as Error).message || "Analysis failed");
      } finally {
        if (ctl.current === c) setAnalysing(false);
      }
    }, 400);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      ctl.current?.abort();
    };
  }, [settled, ensureLoaded, tok, toast]);

  // Climate does not change when the square moves: fetch once per loaded site.
  const siteId = loaded?.site_id ?? null;
  const settledRef = useRef(settled);
  useEffect(() => {
    settledRef.current = settled;
  });
  useEffect(() => {
    if (!siteId) return;
    const c = new AbortController();
    /* eslint-disable react-hooks/set-state-in-effect */
    setClimateLoading(true);
    setClimateError(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    (async () => {
      try {
        let cl: Climate;
        try {
          cl = await fetchClimate(siteId, tok, c.signal);
        } catch (e) {
          const s = settledRef.current;
          if (!(e instanceof ReloadRequired) || !s) throw e;
          const ready = await ensureLoaded(s, c.signal, true);
          cl = await fetchClimate(ready.site_id, tok, c.signal);
        }
        setClimate(cl);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setClimateError((e as Error).message || "Climate request failed");
      } finally {
        if (!c.signal.aborted) setClimateLoading(false);
      }
    })();
    return () => c.abort();
  }, [siteId, climateNonce, tok, ensureLoaded]);

  async function doExport(r: ExportRequest) {
    const s = settled ?? square;
    if (!s) return;
    setExporting(true);
    try {
      const body = (ready: ReadyEvent) => ({ site_id: ready.site_id, lon: s.lon, lat: s.lat, half_width_m: s.halfWidthM, ...r });
      const c = new AbortController();
      let ready = await ensureLoaded(s, c.signal);
      let blob: Blob;
      try {
        blob = await exportZip(body(ready), tok);
      } catch (e) {
        if (!(e instanceof ReloadRequired)) throw e;
        ready = await ensureLoaded(s, c.signal, true);
        blob = await exportZip(body(ready), tok);
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${r.formats.length === 1 && r.formats[0] === "epw" && !r.report ? "weather" : "site"}-${s.lat.toFixed(4)}_${s.lon.toFixed(4)}_${Math.round(s.halfWidthM * 2)}m.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      toast(`Export failed: ${(e as Error).message}`);
    } finally {
      setExporting(false);
    }
  }

  const buildings = useMemo(() => (prev ? annotateBuildings(prev.buildings) : null), [prev]);
  const streets = useMemo(() => (prev ? annotateStreets(prev.streets) : null), [prev]);
  const landuse = useMemo(() => prev?.landuse ?? null, [prev]);
  const contours = useMemo(() => (prev ? annotateContours(prev.contours, prev.contour_interval_m) : null), [prev]);
  const constraints = useMemo(() => (prev ? annotateConstraints(prev.constraints) : null), [prev]);
  const constraintDatasets = useMemo(() => [...new Set((prev?.constraints?.features ?? []).map((f) => String(f.properties?.dataset ?? "")))].filter(Boolean), [prev]);
  const useShares = useMemo(() => typeSourceShares(buildings), [buildings]);
  const typeKnown = useMemo(
    () => (useShares.length ? 1 - (useShares.find((u) => u.id === "none")?.share ?? 0) : null),
    [useShares],
  );
  const landuseClasses = useMemo(() => [...new Set((prev?.landuse?.features ?? []).map((f) => String(f.properties?.class ?? "other")))], [prev]);
  const m = analysis?.metrics;
  const stale = analysing || loading;
  const loadList = Object.values(layers);

  return (
    <main className="relative h-dvh w-full overflow-hidden">
      <MapView
        square={square}
        onSquare={onSquare}
        onPlace={place}
        flyTo={flyTo}
        buildings={buildings}
        streets={streets}
        threeD={threeD}
        mode={layerState.mode}
        overlays={layerState.overlays}
        landuse={landuse}
        contours={contours}
        constraints={constraints}
        onMap={setMap}
        initial={initial}
      />
      <SkyOverlay map={map} square={square} sun={layerState.overlays.sun} wind={layerState.overlays.wind} climate={climate} windMonth={windMonth} />

      {/* top-left: search + view controls */}
      <div className="pointer-events-none absolute left-3 right-3 top-3 z-10 flex max-w-sm flex-col gap-2 sm:right-auto sm:w-80">
        <div className="pointer-events-auto"><Search onPick={pick} /></div>
        <div className="pointer-events-auto glass flex items-center gap-1 self-start rounded-xl p-1" role="group" aria-label="View mode">
          {[false, true].map((v) => (
            <button
              key={String(v)}
              aria-pressed={threeD === v}
              onClick={() => setThreeD(v)}
              className={`rounded-lg px-3 py-1 text-xs font-medium ${threeD === v ? "bg-accent text-accent-fg" : "hover:bg-track"}`}
            >
              {v ? "3D" : "2D"}
            </button>
          ))}
        </div>
        <LayersControl
          layers={layerState}
          onChange={changeLayers}
          legend={<Legend layers={layerState} hasBuildings={!!buildings} constraintDatasets={constraintDatasets} landuseClasses={landuseClasses} useShares={useShares} />}
        />
      </div>

      {/* right panel / mobile bottom sheet */}
      <aside
        className={`glass absolute inset-x-0 bottom-6 z-10 flex flex-col overflow-hidden rounded-t-2xl sm:inset-x-auto sm:bottom-9 sm:right-3 sm:top-3 sm:w-[380px] sm:rounded-2xl ${sheetOpen ? "max-h-[58vh] sm:max-h-none" : "max-h-12 sm:max-h-none"}`}
        aria-label="Site analysis"
      >
        <button
          className="flex items-center justify-between px-4 py-3 text-sm font-semibold sm:hidden"
          onClick={() => setSheetOpen((o) => !o)}
          aria-expanded={sheetOpen}
        >
          <span>{square ? "Site analysis" : "Pick a site"}</span>
          <span aria-hidden>{sheetOpen ? "▾" : "▴"}</span>
        </button>
        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {!square ? (
            <div className="p-4 text-sm text-muted">
              Search for a place, then click the map to drop a square. Drag the centre to move it and the corner handles to resize.
              Live analysis and a building preview appear before you download anything.
            </div>
          ) : (
            <>
              <div className="glass-inset flex gap-1 rounded-xl bg-track p-1" role="tablist" aria-label="Panel">
                {(["analysis", "climate"] as const).map((t) => (
                  <button
                    key={t}
                    role="tab"
                    aria-selected={tab === t}
                    onClick={() => setTab(t)}
                    className={`flex-1 rounded-lg px-3 py-1 text-xs font-semibold capitalize ${tab === t ? "bg-accent text-accent-fg" : "hover:bg-track"}`}
                  >
                    {t}
                  </button>
                ))}
              </div>
              {tab === "climate" ? (
                <ClimatePanel
                  climate={climate}
                  loading={climateLoading || loading}
                  error={climateError}
                  onRetry={() => setClimateNonce((n) => n + 1)}
                  windMonth={windMonth}
                  onWindMonth={setWindMonth}
                  lat={square.lat}
                  lon={square.lon}
                  onDownloadEpw={() => doExport({ formats: ["epw"], report: false })}
                  epwBusy={exporting}
                />
              ) : (
              <>
              <SquareCard square={square} onChange={(s) => onSquare(s, true)} />
              {(loading || loadList.length > 0) && loading && (
                <section className="rounded-xl border border-line p-3" aria-live="polite">
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Loading site data</h3>
                  <ul className="space-y-1 text-xs">
                    {loadList.map((l) => (
                      <li key={l.layer} className="flex items-center gap-2">
                        <span className={l.ok ? "text-green-500" : "text-red-500"}>{l.ok ? "✓" : "✕"}</span>
                        <span className="capitalize">{l.layer}</span>
                        <span className="ml-auto text-muted">{l.provider ?? ""}{typeof l.features === "number" ? ` · ${l.features}` : ""}</span>
                      </li>
                    ))}
                    <li className="flex items-center gap-2 text-muted"><span className="skeleton h-3 w-3 rounded-full" />fetching…</li>
                  </ul>
                </section>
              )}
              <CompletenessCard a={analysis} typeKnown={typeKnown} />
              <ExportPanel busy={exporting} disabled={!loaded || !settled} onExport={doExport} />
              <DensityCard m={m?.fabric} loading={stale} stale={stale && !!m} />
              <StreetsCard m={m?.street} loading={stale} stale={stale && !!m} />
              <LandUseCard m={m?.landuse} loading={stale} stale={stale && !!m} />
              <TerrainCard m={m?.terrain} loading={stale} stale={stale && !!m} />
              <AccessCard m={m?.access} loading={stale} stale={stale && !!m} />
              <ClimateCard m={m?.climate} loading={stale} stale={stale && !!m} />
              <ConstraintsCard m={m?.constraints} />
              </>
              )}
            </>
          )}
        </div>
      </aside>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex items-center gap-2 px-3 py-0.5 text-[10px] text-muted">
        <span className="pointer-events-auto rounded bg-glass px-1.5 py-0.5 backdrop-blur">
          © OpenStreetMap contributors (ODbL) · OpenFreeMap · Photon
        </span>
        {!CLERK_ENABLED && (
          <span className="pointer-events-auto rounded bg-amber-500/20 px-1.5 py-0.5 font-medium text-amber-700 dark:text-amber-300">
            Dev mode: auth disabled
          </span>
        )}
      </div>

      <div className="pointer-events-none absolute bottom-12 left-1/2 z-20 flex -translate-x-1/2 flex-col gap-2" role="status" aria-live="assertive">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto glass max-w-sm rounded-xl border-red-500/40 px-4 py-2 text-sm text-red-600 dark:text-red-400">
            {t.msg}
          </div>
        ))}
      </div>
    </main>
  );
}
