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
  annotateContext,
  annotateContours,
  annotateStreets,
  DEFAULT_LAYERS,
  loadLayers,
  typeSourceShares,
  saveLayers,
  type LayerState,
} from "@/lib/layers";
import { clampHalf, moveCentre, withinPadded, zoomToFit, type SquareState } from "@/lib/square";
import type { Analysis, Climate, LayerEvent, Preview, ReadyEvent } from "@/lib/types";
import { acceptEvent, mergePreview, pendingLabels } from "@/lib/progressive";
import { subsetPreview } from "@/lib/subset";
import { Search } from "./Search";
import { LoadPill } from "./LoadPill";
import { LegendCard, LayersControl } from "./LayersControl";
import { SkyOverlay } from "./SkyOverlay";
import { Sky3D } from "./Sky3D";
import { windRose } from "@/lib/climate";
import { approxOffsetH } from "@/lib/sunpath";
import { useDark } from "@/lib/theme";
import { SitePanel, type Tab } from "./SitePanel";
import type { ExportRequest } from "./ExportPanel";
import { parseHeightShares, sharesFromBuildings } from "@/lib/buildings";
import { reverseName, type SiteName } from "@/lib/site-name";

const MapView = dynamic(() => import("./MapView"), { ssr: false });

const DEFAULT_HALF = 250;

/** One-click 3D views, as in CAD: plan, four axonometric-style views from each corner, and street level. */
const VIEWS: { label: string; title: string; bearing?: number; pitch: number }[] = [
  { label: "Plan", title: "Top view, north up", bearing: 0, pitch: 0 },
  { label: "SW", title: "From the south-west", bearing: 45, pitch: 55 },
  { label: "SE", title: "From the south-east", bearing: -45, pitch: 55 },
  { label: "NE", title: "From the north-east", bearing: -135, pitch: 55 },
  { label: "NW", title: "From the north-west", bearing: 135, pitch: 55 },
  { label: "Street", title: "Eye level, keeping the current direction", pitch: 78 },
];
const WORLD = { lon: 10, lat: 30, zoom: 1.6 };

interface Toast {
  id: number;
  msg: string;
  action?: { label: string; run: () => void };
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
  const dark = useDark();
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; zoom?: number; nonce: number } | null>(null);
  const [initial, setInitial] = useState(WORLD);
  const [exporting, setExporting] = useState(false);
  const [layerState, setLayerState] = useState<LayerState>(DEFAULT_LAYERS);
  const [tab, setTab] = useState<Tab>("analysis");
  const [name, setName] = useState<SiteName | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [climate, setClimate] = useState<Climate | null>(null);
  const [climateLoading, setClimateLoading] = useState(false);
  const [climateError, setClimateError] = useState<string | null>(null);
  const [climateNonce, setClimateNonce] = useState(0);
  const [windMonth, setWindMonth] = useState<number | null>(null);
  const rose3d = useMemo(() => {
    const h = climate?.typical_year.hourly;
    return threeD && layerState.overlays.wind && h ? windRose(h.wind_speed_ms, h.wind_direction_deg, windMonth) : null;
  }, [climate, threeD, layerState.overlays.wind, windMonth]);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const ctl = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadedRef = useRef<ReadyEvent | null>(null);
  const loadedAt = useRef<{ lon: number; lat: number } | null>(null);
  /** The last preview the server returned, and the square it was drawn for: what instant subsets are cut from. */
  const fullRef = useRef<{ preview: Preview; square: SquareState } | null>(null);

  const toast = useCallback((msg: string, action?: Toast["action"]) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, action }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 8000 : 6000);
    return id;
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
      setInitial({ lon, lat, zoom: zoomToFit(s.halfWidthM, lat, Math.min(window.innerWidth, window.innerHeight)) });
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

  // Moving the site is the one change that can mean a long reload, so every move offers an undo.
  // Resizing keeps the centre and never asks.
  const lastSettled = useRef<SquareState | null>(null);
  const undoing = useRef(false);
  useEffect(() => {
    const prev = lastSettled.current;
    lastSettled.current = settled;
    if (!settled || !prev || undoing.current) {
      undoing.current = false;
      return;
    }
    if (prev.lon === settled.lon && prev.lat === settled.lat) return;
    toast("Site moved", {
      label: "Undo",
      run: () => {
        undoing.current = true;
        setSquare(prev);
        setSettled(prev);
        setFlyTo({ lon: prev.lon, lat: prev.lat, zoom: zoomToFit(prev.halfWidthM, prev.lat, Math.min(window.innerWidth, window.innerHeight)), nonce: Date.now() });
      },
    });
  }, [settled, toast]);

  const halfRef = useRef(DEFAULT_HALF);
  useEffect(() => {
    if (square) halfRef.current = square.halfWidthM;
  }, [square]);
  const pick = useCallback(
    (lon: number, lat: number) => {
      place(lon, lat);
      // Frame the whole square, so its grips are on screen.
      setFlyTo({ lon, lat, zoom: zoomToFit(halfRef.current, lat, Math.min(window.innerWidth, window.innerHeight)), nonce: Date.now() });
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
      // A fresh load draws from scratch, layer by layer, as each event brings its geometry.
      setPrev(null);
      fullRef.current = null;
      const real = new Set<string>();
      try {
        const ready = await loadSite(
          s.lon,
          s.lat,
          s.halfWidthM,
          tok,
          (l) => {
            // A draft from map tiles shows first and is replaced by the layer's real event; one
            // that arrives after the real layer is stale.
            if (!acceptEvent(real, l)) return;
            // The buildings update re-reports a layer already listed: keep its first timing.
            if (!l.update) setLayers((m) => ({ ...m, [l.layer]: l }));
            if (l.geojson) setPrev((cur) => mergePreview(cur, l.geojson));
          },
          signal,
        );
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

  /** Run a request against the loaded site; if the server forgot it (409), reload once and retry. */
  const withReload = useCallback(
    async <T,>(s: SquareState, signal: AbortSignal, run: (ready: ReadyEvent) => Promise<T>, start?: ReadyEvent | null): Promise<T> => {
      const ready = start ?? (await ensureLoaded(s, signal));
      try {
        return await run(ready);
      } catch (e) {
        if (!(e instanceof ReloadRequired)) throw e;
        return run(await ensureLoaded(s, signal, true));
      }
    },
    [ensureLoaded],
  );

  // run analysis once the square settles (debounced)
  useEffect(() => {
    if (!settled) return;
    const s = settled;
    const q = new URLSearchParams({ lat: s.lat.toFixed(6), lon: s.lon.toFixed(6), size: String(Math.round(s.halfWidthM * 2)) });
    window.history.replaceState(null, "", `?${q}`);

    // Inside what is already drawn: redraw now from the data in hand, then let the server refine it.
    const have = fullRef.current;
    const quick = have ? subsetPreview(have.preview, have.square, s) : null;
    if (quick) {
      setPrev(quick);
      setAnalysing(true); // figures belong to the old square until analyse returns
    }

    timer.current = setTimeout(async () => {
      const c = new AbortController();
      ctl.current = c;
      try {
        await withReload(s, c.signal, async (ready) => {
          const p: SiteParams = { site_id: ready.site_id, lon: s.lon, lat: s.lat, half_width_m: s.halfWidthM };
          setAnalysing(true);
          // Each answer lands as soon as it arrives: the map should not wait for the figures.
          return Promise.all([
            analyse(p, tok, c.signal).then(setAnalysis),
            fetchPreview(p, tok, c.signal).then((pv) => {
              fullRef.current = { preview: pv, square: s };
              setPrev(pv);
            }),
          ]);
        });
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
  }, [settled, withReload, tok, toast]);

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
        const s = settledRef.current;
        if (!s) return;
        const cl = await withReload(s, c.signal, (ready) => fetchClimate(ready.site_id, tok, c.signal), loadedRef.current);
        setClimate(cl);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setClimateError((e as Error).message || "Climate request failed");
      } finally {
        if (!c.signal.aborted) setClimateLoading(false);
      }
    })();
    return () => c.abort();
  }, [siteId, climateNonce, tok, withReload]);

  async function doExport(r: ExportRequest) {
    const s = settled ?? square;
    if (!s) return;
    setExporting(true);
    try {
      const ready = await ensureLoaded(s, new AbortController().signal);
      const blob = await exportZip({ site_id: ready.site_id, lon: s.lon, lat: s.lat, half_width_m: s.halfWidthM, ...r }, tok);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${r.formats.length === 1 && r.formats[0] === "epw" && !r.report ? "quadrat-weather" : "quadrat"}-${s.lat.toFixed(4)}_${s.lon.toFixed(4)}_${Math.round(s.halfWidthM * 2)}m.zip`;
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
  const context = useMemo(() => (prev?.context ? annotateContext(prev.context) : null), [prev]);
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
  const heightShares = useMemo(
    () => parseHeightShares(analysis?.metrics.fabric?.height_source_shares) ?? sharesFromBuildings(buildings),
    [analysis, buildings],
  );
  const landuseClasses = useMemo(() => [...new Set((prev?.landuse?.features ?? []).map((f) => String(f.properties?.class ?? "other")))], [prev]);
  const stale = analysing || loading;
  const pending = useMemo(() => pendingLabels(layers), [layers]);

  // Name the site: reverse-geocode once the square settles, cached by rounded position.
  useEffect(() => {
    if (!settled) return;
    const c = new AbortController();
    const t = setTimeout(() => {
      reverseName(settled.lon, settled.lat, c.signal)
        .then((n) => setName(n))
        .catch(() => {
          if (!c.signal.aborted) setName(null);
        });
    }, 500);
    return () => {
      clearTimeout(t);
      c.abort();
    };
  }, [settled]);

  return (
    <main className="relative h-dvh w-full overflow-hidden">
      <MapView
        square={square}
        onSquare={onSquare}
        onPlace={place}
        flyTo={flyTo}
        buildings={buildings}
        context={context}
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
      {/* 2D: a flat drawing on the plan. 3D: the sun path rises off the ground as a dome and the
          wind rose rings it on the ground, both projected with the map's own camera. */}
      <SkyOverlay map={map} square={square} sun={layerState.overlays.sun && !threeD} wind={layerState.overlays.wind && !threeD} climate={climate} windMonth={windMonth} />
      {threeD && (
        <Sky3D
          map={map}
          square={square}
          sun={layerState.overlays.sun}
          rose={rose3d}
          offsetH={climate?.timezone.standard_offset_h ?? (square ? approxOffsetH(square.lon) : 0)}
          dark={dark}
        />
      )}

      {/* top-left: search, view mode and layers */}
      <div className="pointer-events-none absolute left-3 right-3 top-3 z-10 flex max-w-sm flex-col gap-2 sm:right-auto sm:w-80">
        <div className="pointer-events-auto"><Search onPick={pick} /></div>
        <LayersControl layers={layerState} onChange={changeLayers} threeD={threeD} onThreeD={setThreeD} />
        {threeD && (
          <div className="sheet pointer-events-auto self-start text-[11px]">
            <div className="flex" role="group" aria-label="3D views">
              {VIEWS.map((v) => (
                <button
                  key={v.label}
                  type="button"
                  title={v.title}
                  className="border-r border-rule px-2 py-1 last:border-r-0 hover:bg-hover"
                  onClick={() => square && map?.easeTo({ center: [square.lon, square.lat], bearing: v.bearing ?? map.getBearing(), pitch: v.pitch, duration: 700 })}
                >
                  {v.label}
                </button>
              ))}
            </div>
            <p className="border-t border-rule px-2 py-1 text-graphite">
              Orbit: <kbd className="font-semibold text-ink">⌥</kbd> + two-finger scroll, or right-drag
            </p>
          </div>
        )}
      </div>

      {/* bottom-left: legend above the dev pill; the map's attribution sits at the bottom edge beside them */}
      <div className="pointer-events-none absolute bottom-[calc(var(--peek)+2.25rem)] left-3 z-10 flex flex-col items-start gap-2 sm:bottom-14">
        {!!buildings && square && (
          <LegendCard
            layers={layerState}
            hasBuildings={!!buildings}
            hasContext={!!context?.features.length}
            constraintDatasets={constraintDatasets}
            landuseClasses={landuseClasses}
            useShares={useShares}
          />
        )}
        {!CLERK_ENABLED && (
          <span className="pointer-events-auto border border-edge bg-sheet px-2 py-0.5 text-[11px] font-semibold">Dev mode: auth disabled</span>
        )}
      </div>

      <LoadPill pending={loading ? pending : []} />

      <SitePanel
        square={square}
        onSquare={(s) => onSquare(s, true)}
        name={name}
        analysis={analysis}
        preview={prev}
        shares={heightShares}
        typeKnown={typeKnown}
        stale={stale}
        loading={loading}
        layers={layers}
        tab={tab}
        onTab={setTab}
        climate={{
          climate,
          loading: climateLoading || loading,
          error: climateError,
          onRetry: () => setClimateNonce((n) => n + 1),
          windMonth,
          onWindMonth: setWindMonth,
          lat: square?.lat ?? 0,
          lon: square?.lon ?? 0,
          onDownloadEpw: () => doExport({ formats: ["epw"], report: false }),
          epwBusy: exporting,
        }}
        exporting={exporting}
        canExport={!!loaded && !!settled}
        onExport={doExport}
      />

      <div className="pointer-events-none absolute inset-x-3 bottom-[calc(var(--peek)+1rem)] z-30 flex flex-col items-center gap-2 sm:bottom-6" role="status" aria-live="assertive">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto sheet flex max-w-sm items-center gap-4 border-red-line px-4 py-2 text-sm">
            {t.msg}
            {t.action && (
              <button
                type="button"
                className="font-semibold underline underline-offset-2 hover:no-underline"
                onClick={() => {
                  t.action?.run();
                  setToasts((all) => all.filter((x) => x.id !== t.id));
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
