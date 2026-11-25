"use client";

import { useEffect, useReducer, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { windRose } from "@/lib/climate";
import { approxOffsetH, sunPosition } from "@/lib/sunpath";
import type { Climate } from "@/lib/types";
import type { SquareState } from "@/lib/square";
import { MAP_INK, SunPathLayer, WindRoseLayer } from "./charts/SkyCharts";

/** SVG overlay centred on the square: sun path and/or wind rose, re-projected on every map move. */
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
  const radiusM = square.halfWidthM * 1.2;
  const c = map.project([square.lon, square.lat]);
  const dLon = radiusM / (111_320 * Math.cos((square.lat * Math.PI) / 180));
  const e = map.project([square.lon + dLon, square.lat]);
  const px = Math.hypot(e.x - c.x, e.y - c.y);
  if (!Number.isFinite(px) || px < 20) return null;
  const k = px / 100;
  const offset = climate?.timezone.standard_offset_h ?? approxOffsetH(square.lon);
  const nowSun = sunPosition(now, square.lat, square.lon);

  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      <g transform={`translate(${c.x} ${c.y}) scale(${k})`}>
        {sun && <SunPathLayer lat={square.lat} lon={square.lon} offsetH={offset} scale={k} labels={px > 90} ink={MAP_INK} nowSun={nowSun} />}
        {rose && rose.total > 0 && (
          <g opacity={0.85} transform={sun ? "scale(0.7)" : undefined}>
            <WindRoseLayer rose={rose} scale={sun ? k * 0.7 : k} labels={px > 90 && !sun} ink={MAP_INK} />
          </g>
        )}
      </g>
    </svg>
  );
}
