"use client";

import { useEffect, useMemo, useRef } from "react";
import { MercatorCoordinate, type CustomLayerInterface, type Map as MapLibreMap } from "maplibre-gl";
import { WIND_COLOURS, type WindRose } from "@/lib/climate";
import { sunRadiusM, windRingM } from "@/lib/overlay";
import { domePoint, makeProjector, projectedPath, sunDome, windRing3D, type V3 } from "@/lib/sundome";
import { sunPosition } from "@/lib/sunpath";
import type { SquareState } from "@/lib/square";
import { mapInk, SUN_COLOURS } from "./charts/SkyCharts";

const LAYER_ID = "sky-3d";
const SVG_NS = "http://www.w3.org/2000/svg";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

/**
 * The sky overlays for the 3D view: the sun path as a dome over the site and the wind rose as a
 * ring on the ground around it.
 *
 * A MapLibre custom layer hands us the camera matrix on every frame it draws; we project both with
 * it and rewrite an SVG laid over the canvas in that same frame, so they stay locked to the
 * buildings while orbiting and stay crisp at any pitch (a flat SVG stretched in perspective blurs).
 * Nothing is drawn in WebGL, so buildings do not hide the dome.
 */
export function Sky3D({
  map,
  square,
  sun,
  rose,
  offsetH,
  dark,
}: {
  map: MapLibreMap | null;
  square: SquareState | null;
  sun: boolean;
  rose: WindRose | null;
  offsetH: number;
  dark: boolean;
}) {
  const half = square?.halfWidthM ?? 0;
  const R = sunRadiusM(half);
  const dome = useMemo(() => (square && sun ? sunDome(square.lat, square.lon, offsetH, R) : null), [square?.lat, square?.lon, offsetH, R, sun]); // eslint-disable-line react-hooks/exhaustive-deps
  const wind = useMemo(() => {
    if (!rose || !rose.total || !half) return null;
    const ring = windRingM(half);
    return windRing3D(rose.share, ring.innerM, ring.outerM);
  }, [rose, half]);
  const active = !!square && (!!dome || !!wind);
  const state = useRef({ dome, wind, square, R, ink: mapInk(dark), now: new Date() });
  useEffect(() => {
    state.current = { ...state.current, dome, wind, square, R, ink: mapInk(dark) };
    map?.triggerRepaint();
  });

  useEffect(() => {
    if (!map || !active) return;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("aria-hidden", "true");
    svg.style.cssText = "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden";
    const canvasBox = map.getCanvasContainer();
    canvasBox.parentElement?.insertBefore(svg, canvasBox.nextSibling);

    const draw = (matrix: ArrayLike<number>) => {
      const { dome: d, wind: w, square: sq, R: r, ink, now } = state.current;
      if (!sq) {
        svg.innerHTML = "";
        return;
      }
      const origin = MercatorCoordinate.fromLngLat([sq.lon, sq.lat], 0);
      const canvas = map.getCanvas();
      const project = makeProjector(matrix, origin, origin.meterInMercatorCoordinateUnits(), canvas.clientWidth, canvas.clientHeight);
      const path = (pts: V3[], attrs: string, close = false) => {
        const dd = projectedPath(pts, project);
        return dd ? `<path d="${dd}${close ? "Z" : ""}" ${close ? "" : 'fill="none" '}${attrs}/>` : "";
      };
      const label = (v: V3, text: string, fill: string, weight = 400, dy = 0) => {
        const s = project(v);
        if (!s) return "";
        return `<text x="${s.x.toFixed(1)}" y="${(s.y + dy).toFixed(1)}" font-size="11" font-weight="${weight}" text-anchor="middle" fill="${fill}" stroke="${ink.halo}" stroke-width="3" paint-order="stroke" stroke-linejoin="round">${esc(text)}</text>`;
      };
      let out = "";

      // wind rose: on the ground, under the dome
      if (w) {
        for (const ring of w.rings) out += path(ring.pts, `stroke="${ink.grid}" stroke-width="${ring.outer || ring.share === 0 ? 1 : 0.75}"${ring.outer || ring.share === 0 ? "" : ' stroke-dasharray="2 3"'}`);
        for (const s of w.spokes) out += path(s, `stroke="${ink.grid}" stroke-width="0.75"`);
        out += `<g opacity="0.7">`;
        for (const p of w.petals) out += path(p.pts, `fill="${WIND_COLOURS[p.bin]}" stroke="${ink.halo}" stroke-width="0.75"`, true);
        out += `</g>`;
        for (const l of w.labels) out += label(l.p, l.text, ink.ink, 400, 0);
      }

      // sun dome
      if (d) {
        for (const ring of d.rings)
          out += path(ring.pts, `stroke="${ink.grid}" stroke-width="${ring.alt ? 0.75 : 1.2}"${ring.alt ? ' stroke-dasharray="2 3"' : ""}`);
        for (const c of d.hourCurves) out += path(c, `stroke="${ink.grid}" stroke-width="1" opacity="0.8"`);
        // a mast from the site centre to the zenith, so the dome reads as a dome
        out += path([[0, 0, 0], [0, 0, r]], `stroke="${ink.grid}" stroke-width="0.75" stroke-dasharray="2 3"`);
        for (const a of d.arcs) {
          const col = SUN_COLOURS[a.id];
          for (const seg of a.segments) out += path(seg, `stroke="${col}" stroke-width="2"`);
          for (const h of a.hours) {
            const s = project(h.p);
            if (s) out += `<circle cx="${s.x.toFixed(1)}" cy="${s.y.toFixed(1)}" r="2.4" fill="${col}" stroke="${ink.halo}" stroke-width="1"><title>${esc(a.label)}, ${String(h.hour).padStart(2, "0")}:00 local standard time</title></circle>`;
          }
        }
        for (const a of d.arcs) if (a.noon) out += label(a.noon, a.label, SUN_COLOURS[a.id], 600, -8);
        for (const c of d.compass) out += label(c.p, c.label, ink.ink, 600, 4);
        const sun = sunPosition(now, sq.lat, sq.lon);
        if (sun.altitude > 0) {
          const p = domePoint(sun.azimuth, sun.altitude, r);
          out += path([[0, 0, 0], p], `stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4 3"`);
          const s = project(p);
          if (s) out += `<circle cx="${s.x.toFixed(1)}" cy="${s.y.toFixed(1)}" r="6" fill="#fbbf24" stroke="${ink.ink}" stroke-width="1.5"><title>Sun now</title></circle>`;
        }
      }
      svg.innerHTML = out;
    };

    const layer: CustomLayerInterface = {
      id: LAYER_ID,
      type: "custom",
      renderingMode: "3d",
      render: (_gl, args) => draw(args.defaultProjectionData.mainMatrix),
    };
    // isStyleLoaded() stays false while tiles load and style.load may have fired already, so try
    // now and again on every styledata (also after a colour-scheme setStyle drops our layer).
    const add = () => {
      try {
        if (!map.getLayer(LAYER_ID)) map.addLayer(layer);
      } catch {
        /* style not ready yet; the next styledata retries */
      }
    };
    add();
    map.on("styledata", add);
    const tick = setInterval(() => {
      state.current.now = new Date();
      map.triggerRepaint();
    }, 60_000);

    return () => {
      clearInterval(tick);
      map.off("styledata", add);
      if (map.getStyle() && map.getLayer(LAYER_ID)) map.removeLayer(LAYER_ID);
      svg.remove();
    };
  }, [map, active]);

  return null;
}
