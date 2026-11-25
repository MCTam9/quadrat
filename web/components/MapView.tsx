"use client";

import { useEffect, useRef } from "react";
import { Map as MapLibreMap, NavigationControl, ScaleControl, setWorkerUrl } from "maplibre-gl";
import type { MapLayerMouseEvent, MapLayerTouchEvent, GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  BASEMAP,
  BLUEPRINT,
  buildingColour,
  missingFilter,
  MISSING_LINE,
  CONSTRAINT_OTHER,
  CONSTRAINT_STYLES,
  LANDUSE_COLOURS,
  palette,
  RED_LINE,
  STREET_CLASSES,
  type ColourMode,
  type Overlay,
} from "@/lib/layers";
import { moveCentre, resizeFromCorner, squareCorners, squarePolygon, type SquareState } from "@/lib/square";
import { blueprintColour, lumaOf } from "@/lib/blueprint";
import { WheelGestures } from "@/lib/gestures";
import { prefersDark, useDark } from "@/lib/theme";

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
  context: GeoJSON.FeatureCollection | null;
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
  if (map.hasImage(hatchId(key))) return;
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

/** Steepest 3D tilt: low enough to look along a street, short of the horizon where tiles thin out. */
const MAX_PITCH_3D = 80;

/** CAD grip: a filled red square with a thin sheet-coloured keyline so it reads on ink and on the dark sheet. */
function addGrip(map: MapLibreMap, keyline: string) {
  if (map.hasImage("grip")) return;
  const px = 2; // device pixels per CSS pixel
  const size = 12 * px;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = keyline;
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = RED_LINE;
  ctx.fillRect(2 * px, 2 * px, size - 4 * px, size - 4 * px);
  map.addImage("grip", ctx.getImageData(0, 0, size, size), { pixelRatio: px });
}

/** Retint the dark basemap to a monochrome charcoal sheet: same drawing, white ink on #161616. */
function blueprint(map: MapLibreMap) {
  for (const layer of map.getStyle().layers) {
    const id = layer.id;
    const set = (prop: "fill-color" | "fill-outline-color" | "line-color" | "text-color" | "text-halo-color", kind: "fill" | "line" | "text" | "halo") => {
      const v = map.getPaintProperty(id, prop);
      if (typeof v !== "string") return;
      const l = lumaOf(v);
      if (l != null) map.setPaintProperty(id, prop, blueprintColour(id, kind, l));
    };
    if (layer.type === "background") map.setPaintProperty(id, "background-color", BLUEPRINT);
    else if (layer.type === "fill") {
      // The dark style's wood pattern is missing from its own sprite; the flat dark tint replaces it.
      if (map.getPaintProperty(id, "fill-pattern")) map.setPaintProperty(id, "fill-pattern", undefined);
      set("fill-color", "fill");
      set("fill-outline-color", "halo");
    } else if (layer.type === "line") set("line-color", "line");
    else if (layer.type === "symbol") {
      set("text-color", "text");
      set("text-halo-color", "halo");
    }
  }
}

/** Large place names and road shields sit on top of the plan at site scale; keep them for zoomed-out views only. */
const PLAN_CLUTTER = /shield|^airport$|city|country|state/;
function clearPlan(map: MapLibreMap) {
  for (const layer of map.getStyle().layers) if (layer.type === "symbol" && PLAN_CLUTTER.test(layer.id)) map.setLayerZoomRange(layer.id, layer.minzoom ?? 0, 12);
}

function setData(map: MapLibreMap, id: string, data: GeoJSON.FeatureCollection | GeoJSON.Feature) {
  (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
}

export default function MapView(props: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const styleDark = useRef(false);
  const dark = useDark();
  const latest = useRef(props);
  useEffect(() => {
    latest.current = props;
  });

  // init
  useEffect(() => {
    if (!el.current) return;
    const { initial } = latest.current;
    styleDark.current = prefersDark();
    const map = new MapLibreMap({
      container: el.current,
      style: BASEMAP[styleDark.current ? "dark" : "light"],
      center: [initial.lon, initial.lat],
      zoom: initial.zoom,
      // Flat until 3D is on; then low enough to look along the street and up at the sun dome.
      maxPitch: 0,
      // Right-drag (or Ctrl-drag) turns by horizontal movement the same way anywhere on the map;
      // MapLibre's default "circular" mode turns one way above the centre and the other below.
      dragRotate: { movement: "linear" },
      attributionControl: { compact: true, customAttribution: "Photon" },
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");

    // Runs on the first style and again after every setStyle (a colour-scheme change),
    // because a new style drops our sources, layers and images.
    const setup = () => {
      const pal = palette(styleDark.current);
      const colorExpr = buildingColour(latest.current.mode, styleDark.current);
      const font = ["Noto Sans Regular"];

      // Dark mode: recolour the dark basemap's background to the sheet.
      if (styleDark.current) blueprint(map);
      clearPlan(map);

      for (const id of ["landuse", "constraints", "contours", "streets", "context", "buildings", "square", "handles"])
        if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: EMPTY });

      const hidden = { visibility: "none" } as const;
      map.addLayer({
        id: "landuse-fill", type: "fill", source: "landuse", layout: hidden,
        paint: {
          "fill-color": ["match", ["get", "class"], ...Object.entries(LANDUSE_COLOURS).filter(([k]) => k !== "other").flat(), LANDUSE_COLOURS.other] as never,
          "fill-opacity": styleDark.current ? 0.5 : 0.55,
        },
      });
      const cStyle = (st: { color: string; colorDark: string }) => (styleDark.current ? st.colorDark : st.color);
      const ckeys = [...Object.entries(CONSTRAINT_STYLES), ["other", CONSTRAINT_OTHER] as const];
      for (const [k, st] of ckeys) addHatch(map, k, cStyle(st));
      const byKey = (f: (k: string, st: { color: string; colorDark: string }) => string) =>
        ["match", ["get", "ckey"], ...ckeys.filter(([k]) => k !== "other").flatMap(([k, st]) => [k, f(k, st)]), f("other", CONSTRAINT_OTHER)] as never;
      map.addLayer({
        id: "constraints-fill", type: "fill", source: "constraints", layout: hidden,
        paint: { "fill-pattern": byKey((k) => hatchId(k)), "fill-opacity": 0.9 },
      });
      map.addLayer({
        id: "constraints-line", type: "line", source: "constraints", layout: hidden,
        paint: { "line-color": byKey((_, st) => cStyle(st)), "line-width": 2, "line-dasharray": [3, 1.5] },
      });
      map.addLayer({
        id: "contours-line", type: "line", source: "contours", layout: hidden,
        paint: {
          "line-color": pal.contour,
          "line-width": ["case", ["==", ["get", "major"], 1], 1.4, 0.6],
          "line-opacity": ["case", ["==", ["get", "major"], 1], 0.9, 0.55],
        },
      });
      map.addLayer({
        id: "streets-line", type: "line", source: "streets",
        paint: { "line-color": pal.streets, "line-width": 0.8, "line-opacity": 0.8 },
      });
      // Context massing: buildings in a ring outside the square, pale graphite.
      map.addLayer({
        id: "context-fill", type: "fill", source: "context",
        paint: { "fill-color": pal.context, "fill-opacity": 1 },
      });
      map.addLayer({
        id: "context-3d", type: "fill-extrusion", source: "context",
        filter: [">", ["get", "h"], 0],
        layout: { visibility: "none" },
        paint: { "fill-extrusion-color": pal.context, "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.95 },
      });
      map.addLayer({
        id: "buildings-fill", type: "fill", source: "buildings",
        paint: { "fill-color": colorExpr as never, "fill-opacity": 1, "fill-outline-color": pal.outline },
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
        paint: { "fill-extrusion-color": colorExpr as never, "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 1 },
      });
      map.addLayer({
        id: "contours-label", type: "symbol", source: "contours", filter: ["==", ["get", "major"], 1],
        layout: { visibility: "none", "symbol-placement": "line", "text-field": ["get", "label"], "text-font": font, "text-size": 11 },
        paint: { "text-color": pal.contourLabel, "text-halo-color": pal.halo, "text-halo-width": 1.5 },
      });
      map.addLayer({
        id: "constraints-label", type: "symbol", source: "constraints",
        layout: { visibility: "none", "text-field": ["get", "label"], "text-font": font, "text-size": 11, "text-max-width": 8 },
        paint: { "text-color": byKey((_, st) => cStyle(st)), "text-halo-color": pal.halo, "text-halo-width": 1.6 },
      });
      // The site: a 2 px red line, no fill.
      map.addLayer({
        id: "square-line", type: "line", source: "square",
        paint: { "line-color": RED_LINE, "line-width": 2 },
      });
      // Invisible, generous hit targets so grips stay reachable by touch.
      map.addLayer({
        id: "handles-hit", type: "circle", source: "handles",
        paint: { "circle-radius": ["match", ["get", "kind"], "centre", 16, 20], "circle-color": "#000000", "circle-opacity": 0 },
      });
      addGrip(map, pal.halo);
      map.addLayer({
        id: "grips", type: "symbol", source: "handles", filter: ["==", ["get", "kind"], "corner"],
        layout: { "icon-image": "grip", "icon-allow-overlap": true, "icon-ignore-placement": true },
      });
      map.addLayer({
        id: "centre", type: "circle", source: "handles", filter: ["==", ["get", "kind"], "centre"],
        paint: { "circle-radius": 4, "circle-color": pal.halo, "circle-opacity": 0.6, "circle-stroke-color": RED_LINE, "circle-stroke-width": 1.5, "circle-stroke-opacity": 0.8 },
      });
      readyRef.current = true;
      sync();
      latest.current.onMap?.(map);
    };
    map.on("style.load", setup);

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
    // Layer-level handlers can't filter by property, so check the feature kind.
    // A corner wins over the centre where their hit areas overlap (very small squares).
    const filtered = (e: MapLayerMouseEvent | MapLayerTouchEvent) => {
      const kinds = (e.features ?? []).map((f) => f.properties?.kind);
      start(kinds.includes("corner") ? "corner" : "centre")(e);
    };
    map.on("mousedown", "handles-hit", filtered);
    map.on("touchstart", "handles-hit", filtered);
    map.on("mousemove", move);
    map.on("touchmove", move);
    map.on("mouseup", end);
    map.on("touchend", end);
    map.on("mouseenter", "handles-hit", () => !dragging && (map.getCanvas().style.cursor = "grab"));
    map.on("mouseleave", "handles-hit", () => !dragging && (map.getCanvas().style.cursor = ""));
    map.on("click", (e) => {
      if (justDragged) return;
      latest.current.onPlace(e.lngLat.lng, e.lngLat.lat);
    });

    // Trackpad gestures: two-finger scroll pans, pinch zooms around the pointer, a mouse wheel
    // still zooms (lib/gestures.ts). Safari reports pinch as gesture events, handled below.
    map.scrollZoom.disable();
    const box = map.getCanvasContainer();
    // Wheel deltas are batched per animation frame: trackpads fire unevenly (and faster than the
    // display), and applying each event straight away is what made orbiting stutter.
    const gestures = new WheelGestures();
    const pending = { dx: 0, dy: 0, dBearing: 0, dPitch: 0 };
    let frame = 0;
    const flush = () => {
      frame = 0;
      if (pending.dx || pending.dy) map.panBy([pending.dx, pending.dy], { animate: false });
      if (pending.dBearing || pending.dPitch)
        map.jumpTo({ bearing: map.getBearing() + pending.dBearing, pitch: map.getPitch() + pending.dPitch });
      pending.dx = pending.dy = pending.dBearing = pending.dPitch = 0;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = box.getBoundingClientRect();
      const act = gestures.next(e as WheelEvent & { wheelDeltaY?: number }, performance.now(), rect.height);
      if (act.kind === "zoom") {
        const around = map.unproject([e.clientX - rect.left, e.clientY - rect.top]);
        map.zoomTo(map.getZoom() + act.dz, { around, animate: false });
        return;
      }
      if (act.kind === "pan") {
        pending.dx += act.dx;
        pending.dy += act.dy;
      } else {
        pending.dBearing += act.dBearing;
        pending.dPitch += act.dPitch;
      }
      if (!frame) frame = requestAnimationFrame(flush);
    };
    let gestureZoom = 0;
    let gestureBearing = 0;
    type Gesture = Event & { scale: number; rotation: number; clientX: number; clientY: number };
    const onGestureStart = (e: Event) => {
      e.preventDefault();
      gestureZoom = map.getZoom();
      gestureBearing = map.getBearing();
    };
    const onGestureChange = (e: Event) => {
      e.preventDefault();
      const g = e as Gesture;
      const rect = box.getBoundingClientRect();
      const around = map.unproject([g.clientX - rect.left, g.clientY - rect.top]);
      // Safari also reports the two-finger twist: turn the map with it.
      map.zoomTo(gestureZoom + Math.log2(g.scale), { around, animate: false });
      map.setBearing(gestureBearing - (g.rotation ?? 0));
    };
    box.addEventListener("wheel", onWheel, { passive: false });
    box.addEventListener("gesturestart", onGestureStart);
    box.addEventListener("gesturechange", onGestureChange);

    return () => {
      box.removeEventListener("wheel", onWheel);
      cancelAnimationFrame(frame);
      box.removeEventListener("gesturestart", onGestureStart);
      box.removeEventListener("gesturechange", onGestureChange);
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
    const isDark = styleDark.current;
    const pal = palette(isDark);
    setData(map, "square", p.square ? squarePolygon(p.square) : EMPTY);
    setData(map, "handles", handlesFor(p.square));
    setData(map, "buildings", p.buildings ?? EMPTY);
    setData(map, "streets", p.streets ?? EMPTY);
    setData(map, "context", p.context ?? EMPTY);
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
    const colour = buildingColour(p.mode, isDark) as never;
    map.setPaintProperty("buildings-fill", "fill-color", colour);
    map.setPaintProperty("buildings-fill", "fill-opacity", p.mode === "none" ? 1 : 0.92);
    map.setPaintProperty("buildings-3d", "fill-extrusion-color", colour);
    map.setFilter("buildings-missing", missingFilter(p.mode) as never);
    map.setFilter("buildings-missing-line", missingFilter(p.mode) as never);
    if (p.overlays.streets) {
      map.setPaintProperty("streets-line", "line-color", ["match", ["get", "sclass"], ...STREET_CLASSES.flatMap((c) => [c.id, isDark ? c.colorDark : c.color]), pal.streets] as never);
      map.setPaintProperty("streets-line", "line-width", ["match", ["get", "sclass"], ...STREET_CLASSES.flatMap((c) => [c.id, c.width]), 1.4] as never);
      map.setPaintProperty("streets-line", "line-opacity", 0.95);
    } else {
      map.setPaintProperty("streets-line", "line-color", pal.streets);
      map.setPaintProperty("streets-line", "line-width", 0.8);
      map.setPaintProperty("streets-line", "line-opacity", 0.8);
    }
    map.setLayoutProperty("buildings-3d", "visibility", p.threeD ? "visible" : "none");
    map.setLayoutProperty("context-3d", "visibility", p.threeD ? "visible" : "none");
    // 3D: flat fill only for buildings without a height.
    map.setFilter("buildings-fill", p.threeD ? ["<=", ["get", "h"], 0] : null);
    map.setFilter("context-fill", p.threeD ? ["<=", ["get", "h"], 0] : null);
  }

  useEffect(sync, [props.square, props.buildings, props.streets, props.threeD, props.mode, props.overlays, props.landuse, props.contours, props.constraints, props.context]);

  // Follow the OS colour scheme: swap the basemap, then setup() rebuilds our layers on style.load.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || styleDark.current === dark) return;
    styleDark.current = dark;
    readyRef.current = false;
    map.setStyle(BASEMAP[dark ? "dark" : "light"], { diff: false });
  }, [dark]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (props.threeD) {
      map.setMaxPitch(MAX_PITCH_3D);
      // Orbit pivots on the screen centre, so put the site there: turning then spins the site in place.
      const sq = latest.current.square;
      map.easeTo({ pitch: 55, duration: 600, ...(sq ? { center: [sq.lon, sq.lat] as [number, number] } : {}) });
    } else {
      // Ease down first, then lock the map flat so no gesture can tilt the 2D plan.
      map.easeTo({ pitch: 0, duration: 600 });
      map.once("moveend", () => !latest.current.threeD && map.setMaxPitch(0));
    }
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
