"use client";

import { useEffect, useId, useRef, useState } from "react";
import { downloadLabel, fileCount } from "@/lib/export";
import { EXPORT_FORMATS } from "@/lib/types";

const KEY = "sce.formats";

export interface ExportRequest {
  formats: string[];
  report: boolean;
}

/** The panel footer: pick formats in a popover, then one button that says how many files you get. */
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
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();

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
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => {
      clearInterval(timer);
      setElapsed(0);
    };
  }, [busy]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const toggle = (f: string) => setFormats((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));
  const none = fileCount(formats, report) === 0;
  const chosen = [...EXPORT_FORMATS.filter((f) => formats.includes(f.id)).map((f) => f.label), ...(report ? ["PDF"] : [])].join(", ");

  return (
    <div ref={root} className="relative border-t border-edge p-3">
      {open && (
        <div id={id} className="sheet absolute inset-x-3 bottom-full mb-1 p-2" role="group" aria-label="Download formats">
          <div className="grid grid-cols-2 gap-x-3">
            {EXPORT_FORMATS.map((f) => (
              <label key={f.id} className="flex cursor-pointer items-center gap-2 px-1 py-1.5 text-xs hover:bg-hover">
                <input type="checkbox" checked={formats.includes(f.id)} onChange={() => toggle(f.id)} />
                <span className="font-semibold">{f.label}</span>
                <span className="ml-auto truncate text-graphite">{f.hint}</span>
              </label>
            ))}
            <label className="col-span-2 flex cursor-pointer items-center gap-2 px-1 py-1.5 text-xs hover:bg-hover">
              <input type="checkbox" checked={report} onChange={(e) => setReport(e.target.checked)} />
              <span className="font-semibold">PDF report</span>
              <span className="ml-auto text-graphite">Site analysis</span>
            </label>
          </div>
        </div>
      )}
      <button
        type="button"
        className="mb-2 flex w-full items-center gap-2 text-left text-xs hover:underline"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-graphite">Formats</span>
        <span className="truncate font-semibold">{chosen || "None selected"}</span>
        <svg className={`ml-auto h-3 w-3 shrink-0 transition-transform ${open ? "" : "rotate-180"}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <path d="M2 4.5 6 8.5 10 4.5" />
        </svg>
      </button>
      <button
        disabled={busy || disabled || none}
        onClick={() => onExport({ formats, report })}
        className="w-full bg-ink px-3 py-2.5 text-sm font-semibold text-sheet transition-opacity disabled:opacity-40"
      >
        {busy ? `Building bundle, ${elapsed} s` : downloadLabel(formats, report)}
      </button>
      {disabled && <p className="mt-1.5 text-xs text-graphite">Place the square and wait for site data to load.</p>}
    </div>
  );
}
