"use client";

import { useState } from "react";
import { edgeLengthM, PRESETS_M, setEdgeLength, utmZone, type SquareState } from "@/lib/square";
import { formatCoords } from "@/lib/site-name";
import { sunSummary } from "@/lib/sun";
import { time } from "@/lib/format";
import { Card } from "./Cards";

/** Size and position of the square, as the title block's small definition list. */
export function SquareControls({ square, onChange }: { square: SquareState; onChange: (s: SquareState) => void }) {
  const edge = Math.round(edgeLengthM(square));
  const [draft, setDraft] = useState<string | null>(null);
  const utm = utmZone(square.lon, square.lat);
  const commit = () => {
    const v = parseFloat(draft ?? "");
    if (Number.isFinite(v)) onChange(setEdgeLength(square, v));
    setDraft(null);
  };
  return (
    <dl className="grid grid-cols-[4.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-xs">
      <dt className="text-graphite">Square</dt>
      <dd className="flex items-center gap-2">
        <input
          type="number"
          min={100}
          max={2000}
          step={10}
          inputMode="numeric"
          aria-label="Edge length in metres"
          className="w-16 border border-rule bg-transparent px-1.5 py-1 text-sm nums"
          value={draft ?? edge}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
        />
        <span className="text-graphite">m</span>
        <span className="ml-auto flex gap-1" role="group" aria-label="Size presets">
          {PRESETS_M.map((p) => (
            <button
              key={p}
              onClick={() => onChange(setEdgeLength(square, p))}
              aria-pressed={edge === p}
              className={`border border-rule px-1.5 py-1 nums ${edge === p ? "border-ink bg-ink text-sheet" : "hover:bg-hover"}`}
            >
              {p}
            </button>
          ))}
        </span>
      </dd>
      <dt className="text-graphite">Position</dt>
      <dd className="nums">{formatCoords(square.lat, square.lon)}</dd>
      <dt className="text-graphite">Grid</dt>
      <dd className="nums">
        UTM {utm.zone}
        {utm.hemisphere}, EPSG:{utm.epsg}
      </dd>
    </dl>
  );
}

/** Sunrise, sunset and noon altitude on three reference days. */
export function SunTimes({ square }: { square: SquareState }) {
  const sun = sunSummary(square.lat, square.lon);
  return (
    <Card title="Sun">
      <table className="w-full text-xs nums">
        <thead className="text-left text-graphite">
          <tr>
            <th className="font-normal"></th>
            <th className="font-normal">Rise</th>
            <th className="font-normal">Set</th>
            <th className="font-normal">Noon altitude</th>
          </tr>
        </thead>
        <tbody>
          {sun.map((d) => (
            <tr key={d.label}>
              <td className="py-0.5 text-graphite">{d.label}</td>
              <td>{time(d.sunrise)}</td>
              <td>{time(d.sunset)}</td>
              <td>{d.noonAltitudeDeg.toFixed(1)}°</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
