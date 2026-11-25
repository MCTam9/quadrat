"use client";

import { useEffect, useReducer, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { windRose } from "@/lib/climate";
import { sunRadiusM, windRingM } from "@/lib/overlay";
import { approxOffsetH, sunPosition } from "@/lib/sunpath";
import { useDark } from "@/lib/theme";
import type { Climate } from "@/lib/types";
import type { SquareState } from "@/lib/square";
import { mapInk, SunPathLayer, WindRoseLayer } from "./charts/SkyCharts";

/**
 * SVG overlay centred on the square, re-projected on every map move.
 * The sun path sits inside the square; the wind rose is an outer ring beyond its corners,
 * so both read at once.
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
  const c = map.project([square.lon, square.lat]);
  const dLonPerM = 1 / (111_320 * Math.cos((square.lat * Math.PI) / 180));
  const e = map.project([square.lon + dLonPerM, square.lat]);
  const pxPerM = Math.hypot(e.x - c.x, e.y - c.y);
  const sunPx = sunRadiusM(square.halfWidthM) * pxPerM;
  const ring = windRingM(square.halfWidthM);
  const outerPx = ring.outerM * pxPerM;
  if (!Number.isFinite(sunPx) || sunPx < 20) return null;
  const ks = sunPx / 100;
  const kw = outerPx / 100;
  const offset = climate?.timezone.standard_offset_h ?? approxOffsetH(square.lon);
  const nowSun = sunPosition(now, square.lat, square.lon);
  const ink = mapInk(dark);

  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      <g transform={`translate(${c.x} ${c.y})`}>
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
  );
}
