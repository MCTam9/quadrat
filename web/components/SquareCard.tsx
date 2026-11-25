"use client";

import { useState } from "react";
import { areaKm2, edgeLengthM, PRESETS_M, setEdgeLength, utmZone, type SquareState } from "@/lib/square";
import { sunSummary } from "@/lib/sun";
import { time } from "@/lib/format";
import { Card } from "./Cards";

export function SquareCard({ square, onChange }: { square: SquareState; onChange: (s: SquareState) => void }) {
  const edge = Math.round(edgeLengthM(square));
  const [draft, setDraft] = useState<string | null>(null);
  const utm = utmZone(square.lon, square.lat);
  const sun = sunSummary(square.lat, square.lon);
  const commit = () => {
    const v = parseFloat(draft ?? "");
    if (Number.isFinite(v)) onChange(setEdgeLength(square, v));
    setDraft(null);
  };
  return (
    <Card title="Site square">
      <div className="flex items-end gap-2">
        <label className="flex-1 text-[11px] text-muted">
          Edge length (m)
          <input
            type="number"
            min={100}
            max={2000}
            step={10}
            inputMode="numeric"
            className="mt-0.5 w-full rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg tabular-nums"
            value={draft ?? edge}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => e.key === "Enter" && commit()}
          />
        </label>
        <div className="text-right">
          <div className="text-[11px] text-muted">Area</div>
          <div className="text-base font-semibold tabular-nums">{areaKm2(square).toFixed(2)} <span className="text-xs font-normal text-muted">km²</span></div>
        </div>
      </div>
      <div className="mt-2 flex gap-1.5" role="group" aria-label="Size presets">
        {PRESETS_M.map((p) => (
          <button
            key={p}
            onClick={() => onChange(setEdgeLength(square, p))}
            aria-pressed={edge === p}
            className={`flex-1 rounded-lg border border-line px-1 py-1 text-xs tabular-nums hover:bg-track ${edge === p ? "bg-accent text-accent-fg" : ""}`}
          >
            {p}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted tabular-nums">
        {square.lat.toFixed(5)}, {square.lon.toFixed(5)} · UTM {utm.zone}{utm.hemisphere} (EPSG:{utm.epsg})
      </p>
      <table className="mt-2 w-full text-xs tabular-nums">
        <thead className="text-left text-[11px] text-muted">
          <tr><th className="font-normal"></th><th className="font-normal">Rise</th><th className="font-normal">Set</th><th className="font-normal">Noon alt.</th></tr>
        </thead>
        <tbody>
          {sun.map((d) => (
            <tr key={d.label}>
              <td className="py-0.5 text-muted">{d.label}</td>
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
