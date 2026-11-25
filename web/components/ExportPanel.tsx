"use client";

import { useEffect, useState } from "react";
import { EXPORT_FORMATS } from "@/lib/types";
import { Card } from "./Cards";

const KEY = "sce.formats";

export interface ExportRequest {
  formats: string[];
  report: boolean;
}

export function ExportPanel({
  busy,
  disabled,
  onExport,
}: {
  busy: boolean;
  disabled: boolean;
  onExport: (r: ExportRequest) => void;
}) {
  const [formats, setFormats] = useState<string[]>(["dxf", "geojson"]);
  const [report, setReport] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const j = JSON.parse(raw) as { formats?: string[]; report?: boolean };
        const valid = (j.formats ?? []).filter((f) => EXPORT_FORMATS.some((e) => e.id === f));
        // eslint-disable-next-line react-hooks/set-state-in-effect
        if (valid.length) setFormats(valid);
        if (typeof j.report === "boolean") setReport(j.report);
      }
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ formats, report }));
    } catch {
      /* storage unavailable */
    }
  }, [formats, report]);

  useEffect(() => {
    if (!busy) return;
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => {
      clearInterval(id);
      setElapsed(0);
    };
  }, [busy]);

  const toggle = (id: string) => setFormats((f) => (f.includes(id) ? f.filter((x) => x !== id) : [...f, id]));
  const nothing = formats.length === 0 && !report;

  return (
    <Card title="Download CAD bundle">
      <div className="grid grid-cols-2 gap-1.5">
        {EXPORT_FORMATS.map((f) => (
          <label key={f.id} className="flex cursor-pointer items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-xs hover:bg-track">
            <input type="checkbox" className="accent-[var(--accent)]" checked={formats.includes(f.id)} onChange={() => toggle(f.id)} />
            <span className="font-medium">{f.label}</span>
            <span className="ml-auto text-muted">{f.hint}</span>
          </label>
        ))}
        <label className="col-span-2 flex cursor-pointer items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-xs hover:bg-track">
          <input type="checkbox" className="accent-[var(--accent)]" checked={report} onChange={(e) => setReport(e.target.checked)} />
          <span className="font-medium">PDF report</span>
          <span className="ml-auto text-muted">Site analysis</span>
        </label>
      </div>
      <button
        disabled={busy || disabled || nothing}
        onClick={() => onExport({ formats, report })}
        className="mt-3 w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-accent-fg transition-opacity disabled:opacity-40"
      >
        {busy ? `Building bundle… ${elapsed}s` : "Download ZIP"}
      </button>
      {disabled && <p className="mt-1.5 text-[11px] text-muted">Place the square and wait for site data to load.</p>}
    </Card>
  );
}
