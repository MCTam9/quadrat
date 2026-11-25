"use client";

import { useEffect, useReducer, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { windRose } from "@/lib/climate";
import { isConvexQuad, quadTransform, sunRadiusM, windRingM } from "@/lib/overlay";
import { approxOffsetH, sunPosition } from "@/lib/sunpath";
import { useDark } from "@/lib/theme";
import type { Climate } from "@/lib/types";
import type { SquareState } from "@/lib/square";
import { mapInk, SunPathLayer, WindRoseLayer } from "./charts/SkyCharts";

/**
 * SVG overlay centred on the square, laid on the ground plane and re-projected on every map
 * move, so it tilts and turns with the 3D view (pitch and bearing). The sun path sits inside
 * the square; the wind rose is an outer ring beyond its corners, so both read at once.
 */
export function SkyOverlay({
  map,
  square,
  sun,
  wind,
  climate,
  windMonth,
}: {
  map: MapLibreMap | null;
  square: SquareState | null;
  sun: boolean;
  wind: boolean;
  climate: Climate | null;
  windMonth: number | null;
}) {
  const [, bump] = useReducer((n: number) => n + 1, 0);
  const [now, setNow] = useState(() => new Date());
  const dark = useDark();

  useEffect(() => {
    if (!map) return;
    map.on("move", bump);
    map.on("resize", bump);
    return () => {
      map.off("move", bump);
      map.off("resize", bump);
    };
  }, [map]);

  useEffect(() => {
    if (!sun) return;
    const id = setInterval(() => setNow(new Date()), 60_000);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNow(new Date());
    return () => clearInterval(id);
  }, [sun]);

  const hourly = climate?.typical_year.hourly;
  const rose = hourly && wind ? windRose(hourly.wind_speed_ms, hourly.wind_direction_deg, windMonth) : null;

  if (!map || !square || (!sun && !wind)) return null;
  const mPerDegLat = 111_320;
  const mPerDegLon = mPerDegLat * Math.cos((square.lat * Math.PI) / 180);
  const at = (eastM: number, northM: number) => map.project([square.lon + eastM / mPerDegLon, square.lat + northM / mPerDegLat]);
  const c = at(0, 0);
  const e = at(1, 0);
  const pxPerM = Math.hypot(e.x - c.x, e.y - c.y);
  const sunR = sunRadiusM(square.halfWidthM);
  const ring = windRingM(square.halfWidthM);
  const sunPx = sunR * pxPerM;
  if (!Number.isFinite(sunPx) || sunPx < 20) return null;

  // The drawing lives in a flat box 2L metres across, drawn at the centre's screen scale, then
  // mapped onto the four projected ground corners of that box.
  const L = Math.max(sunR, ring.outerM) * 1.15;
  const size = 2 * L * pxPerM;
  const quad: [typeof c, typeof c, typeof c, typeof c] = [at(-L, L), at(L, L), at(L, -L), at(-L, -L)];
  if (!isConvexQuad(quad)) return null;
  const ks = sunPx / 100;
  const kw = (ring.outerM * pxPerM) / 100;
  const offset = climate?.timezone.standard_offset_h ?? approxOffsetH(square.lon);
  const nowSun = sunPosition(now, square.lat, square.lon);
  const ink = mapInk(dark);

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <svg
        className="absolute left-0 top-0 overflow-visible"
        width={size}
        height={size}
        style={{ transformOrigin: "0 0", transform: quadTransform(size, quad) }}
      >
        <g transform={`translate(${size / 2} ${size / 2})`}>
          {rose && rose.total > 0 && (
            <g transform={`scale(${kw})`}>
              <WindRoseLayer rose={rose} scale={kw} labels={sunPx > 60} ink={ink} inner={(ring.innerM / ring.outerM) * 100} petalOpacity={0.55} />
            </g>
          )}
          {sun && (
            <g transform={`scale(${ks})`}>
              <SunPathLayer lat={square.lat} lon={square.lon} offsetH={offset} scale={ks} labels={sunPx > 60} ink={ink} nowSun={nowSun} />
            </g>
          )}
        </g>
      </svg>
    </div>
  );
}
