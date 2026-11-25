"use client";

import { useEffect, useRef } from "react";
import { Map as MapLibreMap, NavigationControl, ScaleControl, setWorkerUrl } from "maplibre-gl";
import type { MapLayerMouseEvent, MapLayerTouchEvent, GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  buildingColour,
  missingFilter,
  MISSING_LINE,
  CONSTRAINT_OTHER,
  CONSTRAINT_STYLES,
  LANDUSE_COLOURS,
  STREET_CLASSES,
  type ColourMode,
  type Overlay,
} from "@/lib/layers";
import { moveCentre, resizeFromCorner, squareCorners, squarePolygon, type SquareState } from "@/lib/square";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
// Served from public/ by scripts/copy-maplibre-worker.mjs; the bundler breaks the default URL.
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

interface Props {
  square: SquareState | null;
  onSquare: (s: SquareState, final: boolean) => void;
  onPlace: (lon: number, lat: number) => void;
  flyTo: { lon: number; lat: number; zoom?: number; nonce: number } | null;
  buildings: GeoJSON.FeatureCollection | null;
  streets: GeoJSON.FeatureCollection | null;
  threeD: boolean;
  mode: ColourMode;
  overlays: Record<Overlay, boolean>;
  landuse: GeoJSON.FeatureCollection | null;
  contours: GeoJSON.FeatureCollection | null;
  constraints: GeoJSON.FeatureCollection | null;
  onMap?: (m: MapLibreMap | null) => void;
  initial: { lon: number; lat: number; zoom: number };
}

function handlesFor(s: SquareState | null): GeoJSON.FeatureCollection {
  if (!s) return EMPTY;
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { kind: "centre" }, geometry: { type: "Point", coordinates: [s.lon, s.lat] } },
      ...squareCorners(s).map((c) => ({
        type: "Feature" as const,
        properties: { kind: "corner" },
        geometry: { type: "Point" as const, coordinates: c },
      })),
    ],
  };
}

const hatchId = (k: string) => `hatch-${k}`;

/** Diagonal-hatch tile in one colour, registered as a map image for fill-pattern. */
function addHatch(map: MapLibreMap, key: string, color: string) {
  const n = 12;
  const c = document.createElement("canvas");
  c.width = c.height = n;
  const ctx = c.getContext("2d");
  if (!ctx) return;
  ctx.strokeStyle = color;
  ctx.globalAlpha = 0.75;
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  for (const o of [-n, 0, n]) {
    ctx.moveTo(o, n);
    ctx.lineTo(o + n, 0);
  }
  ctx.stroke();
  map.addImage(hatchId(key), ctx.getImageData(0, 0, n, n));
}

function setData(map: MapLibreMap, id: string, data: GeoJSON.FeatureCollection | GeoJSON.Feature) {
  (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
}

export default function MapView(props: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const latest = useRef(props);
  useEffect(() => {
    latest.current = props;
  });

  // init
  useEffect(() => {
    if (!el.current) return;
    const { initial } = latest.current;
    const map = new MapLibreMap({
      container: el.current,
      style: STYLE,
      center: [initial.lon, initial.lat],
      zoom: initial.zoom,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");

    map.on("load", () => {
      const colorExpr = buildingColour(latest.current.mode);
      const font = ["Noto Sans Regular"];

      map.addSource("landuse", { type: "geojson", data: EMPTY });
      map.addSource("constraints", { type: "geojson", data: EMPTY });
      map.addSource("contours", { type: "geojson", data: EMPTY });
      map.addSource("streets", { type: "geojson", data: EMPTY });
      map.addSource("buildings", { type: "geojson", data: EMPTY });
      map.addSource("square", { type: "geojson", data: EMPTY });
      map.addSource("handles", { type: "geojson", data: EMPTY });

      const hidden = { visibility: "none" } as const;
      map.addLayer({
        id: "landuse-fill", type: "fill", source: "landuse", layout: hidden,
        paint: {
          "fill-color": ["match", ["get", "class"], ...Object.entries(LANDUSE_COLOURS).filter(([k]) => k !== "other").flat(), LANDUSE_COLOURS.other] as never,
          "fill-opacity": 0.55,
        },
      });
      const ckeys = [...Object.entries(CONSTRAINT_STYLES), ["other", CONSTRAINT_OTHER] as const];
      for (const [k, st] of ckeys) addHatch(map, k, st.color);
      const byKey = (f: (k: string, st: { color: string }) => string) =>
        ["match", ["get", "ckey"], ...ckeys.filter(([k]) => k !== "other").flatMap(([k, st]) => [k, f(k, st)]), f("other", CONSTRAINT_OTHER)] as never;
      map.addLayer({
        id: "constraints-fill", type: "fill", source: "constraints", layout: hidden,
        paint: { "fill-pattern": byKey((k) => hatchId(k)), "fill-opacity": 0.9 },
      });
      map.addLayer({
        id: "constraints-line", type: "line", source: "constraints", layout: hidden,
        paint: { "line-color": byKey((_, st) => st.color), "line-width": 2, "line-dasharray": [3, 1.5] },
      });
      map.addLayer({
        id: "contours-line", type: "line", source: "contours", layout: hidden,
        paint: {
          "line-color": "#92400e",
          "line-width": ["case", ["==", ["get", "major"], 1], 1.4, 0.6],
          "line-opacity": ["case", ["==", ["get", "major"], 1], 0.9, 0.55],
        },
      });
      map.addLayer({
        id: "streets-line", type: "line", source: "streets",
        paint: { "line-color": "#64748b", "line-width": 0.8, "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "buildings-fill", type: "fill", source: "buildings",
        paint: { "fill-color": colorExpr as never, "fill-opacity": 0.85, "fill-outline-color": "#ffffff" },
      });
      // Missing data for the active colour mode: crimson hatch over the rose fill,
      // so a gap in the data never passes for a quiet grey value.
      addHatch(map, "missing", MISSING_LINE);
      map.addLayer({
        id: "buildings-missing", type: "fill", source: "buildings",
        filter: missingFilter(latest.current.mode) as never,
        paint: { "fill-pattern": hatchId("missing"), "fill-opacity": 1 },
      });
      map.addLayer({
        id: "buildings-missing-line", type: "line", source: "buildings",
        filter: missingFilter(latest.current.mode) as never,
        paint: { "line-color": MISSING_LINE, "line-width": 1, "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "buildings-3d", type: "fill-extrusion", source: "buildings",
        filter: [">", ["get", "h"], 0],
        layout: { visibility: "none" },
        paint: { "fill-extrusion-color": colorExpr as never, "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.92 },
      });
      map.addLayer({
        id: "contours-label", type: "symbol", source: "contours", filter: ["==", ["get", "major"], 1],
        layout: { visibility: "none", "symbol-placement": "line", "text-field": ["get", "label"], "text-font": font, "text-size": 10 },
        paint: { "text-color": "#78350f", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      });
      map.addLayer({
        id: "constraints-label", type: "symbol", source: "constraints",
        layout: { visibility: "none", "text-field": ["get", "label"], "text-font": font, "text-size": 11, "text-max-width": 8 },
        paint: { "text-color": byKey((_, st) => st.color), "text-halo-color": "#ffffff", "text-halo-width": 1.6 },
      });
      map.addLayer({
        id: "square-fill", type: "fill", source: "square",
        paint: { "fill-color": "#4f46e5", "fill-opacity": 0.08 },
      });
      map.addLayer({
        id: "square-line", type: "line", source: "square",
        paint: { "line-color": "#4f46e5", "line-width": 2 },
      });
      map.addLayer({
        id: "handles", type: "circle", source: "handles",
        paint: {
          "circle-radius": ["match", ["get", "kind"], "centre", 8, 7],
          "circle-color": ["match", ["get", "kind"], "centre", "#4f46e5", "#ffffff"],
          "circle-stroke-color": "#4f46e5",
          "circle-stroke-width": 2.5,
        },
      });
      readyRef.current = true;
      sync();
      latest.current.onMap?.(map);
    });

    // drag handling
    let dragging: "centre" | "corner" | null = null;
    let justDragged = false;
    const start = (kind: "centre" | "corner") => (e: MapLayerMouseEvent | MapLayerTouchEvent) => {
      e.preventDefault();
      dragging = kind;
      map.dragPan.disable();
      map.getCanvas().style.cursor = "grabbing";
    };
    const move = (e: { lngLat: { lng: number; lat: number } }) => {
      const s = latest.current.square;
      if (!dragging || !s) return;
      const next =
        dragging === "centre"
          ? moveCentre(s, e.lngLat.lng, e.lngLat.lat)
          : resizeFromCorner(s, [e.lngLat.lng, e.lngLat.lat]);
      latest.current.onSquare(next, false);
    };
    const end = () => {
      if (!dragging) return;
      dragging = null;
      justDragged = true;
      setTimeout(() => (justDragged = false), 50);
      map.dragPan.enable();
      map.getCanvas().style.cursor = "";
      const s = latest.current.square;
      if (s) latest.current.onSquare(s, true);
    };
    for (const kind of ["centre", "corner"] as const) {
      // Layer-level handlers can't filter by property, so check the feature kind.
      const filtered = (e: MapLayerMouseEvent | MapLayerTouchEvent) => {
        if (e.features?.[0]?.properties?.kind === kind) start(kind)(e);
      };
      map.on("mousedown", "handles", filtered);
      map.on("touchstart", "handles", filtered);
    }
    map.on("mousemove", move);
    map.on("touchmove", move);
    map.on("mouseup", end);
    map.on("touchend", end);
    map.on("mouseenter", "handles", () => !dragging && (map.getCanvas().style.cursor = "grab"));
    map.on("mouseleave", "handles", () => !dragging && (map.getCanvas().style.cursor = ""));
    map.on("click", (e) => {
      if (justDragged) return;
      latest.current.onPlace(e.lngLat.lng, e.lngLat.lat);
    });

    return () => {
      readyRef.current = false;
      latest.current.onMap?.(null);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  function sync() {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const p = latest.current;
    setData(map, "square", p.square ? squarePolygon(p.square) : EMPTY);
    setData(map, "handles", handlesFor(p.square));
    setData(map, "buildings", p.buildings ?? EMPTY);
    setData(map, "streets", p.streets ?? EMPTY);
    setData(map, "landuse", p.landuse ?? EMPTY);
    setData(map, "contours", p.contours ?? EMPTY);
    setData(map, "constraints", p.constraints ?? EMPTY);
    const vis = (id: string, on: boolean) => map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    vis("landuse-fill", p.overlays.landuse);
    vis("contours-line", p.overlays.contours);
    vis("contours-label", p.overlays.contours);
    vis("constraints-fill", p.overlays.constraints);
    vis("constraints-line", p.overlays.constraints);
    vis("constraints-label", p.overlays.constraints);
    const colour = buildingColour(p.mode) as never;
    map.setPaintProperty("buildings-fill", "fill-color", colour);
    map.setPaintProperty("buildings-3d", "fill-extrusion-color", colour);
    map.setFilter("buildings-missing", missingFilter(p.mode) as never);
    map.setFilter("buildings-missing-line", missingFilter(p.mode) as never);
    if (p.overlays.streets) {
      map.setPaintProperty("streets-line", "line-color", ["match", ["get", "sclass"], ...STREET_CLASSES.flatMap((c) => [c.id, c.color]), "#475569"] as never);
      map.setPaintProperty("streets-line", "line-width", ["match", ["get", "sclass"], ...STREET_CLASSES.flatMap((c) => [c.id, c.width]), 1.4] as never);
      map.setPaintProperty("streets-line", "line-opacity", 0.95);
    } else {
      map.setPaintProperty("streets-line", "line-color", "#64748b");
      map.setPaintProperty("streets-line", "line-width", 0.8);
      map.setPaintProperty("streets-line", "line-opacity", 0.8);
    }
    map.setLayoutProperty("buildings-3d", "visibility", p.threeD ? "visible" : "none");
    // 3D: flat fill only for buildings without a height.
    map.setFilter("buildings-fill", p.threeD ? ["<=", ["get", "h"], 0] : null);
  }

  useEffect(sync, [props.square, props.buildings, props.streets, props.threeD, props.mode, props.overlays, props.landuse, props.contours, props.constraints]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.easeTo({ pitch: props.threeD ? 55 : 0, duration: 600 });
  }, [props.threeD]);

  useEffect(() => {
    const map = mapRef.current;
    const f = props.flyTo;
    if (map && f) map.flyTo({ center: [f.lon, f.lat], zoom: f.zoom ?? 15, duration: 1200 });
  }, [props.flyTo]);

  // MapLibre's (unlayered) CSS forces position:relative on the map element, which beats
  // Tailwind's layered `absolute`, so the positioning lives on a wrapper.
  return (
    <div className="absolute inset-0">
      <div ref={el} className="h-full w-full" aria-label="Map" />
    </div>
  );
}
