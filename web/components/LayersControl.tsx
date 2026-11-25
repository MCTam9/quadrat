"use client";

import { useId, useState } from "react";
import {
  CONSTRAINT_OTHER,
  CONSTRAINT_STYLES,
  modeLegend,
  LANDUSE_COLOURS,
  LANDUSE_LABELS,
  MODES,
  OVERLAYS,
  STREET_CLASSES,
  USE_SOURCE_LABELS,
  type UseSource,
  type ColourMode,
  type LayerState,
  type Overlay,
} from "@/lib/layers";

function Swatch({ color, hatch }: { color: string; hatch?: boolean }) {
  return (
    <span
      className="h-3 w-3 shrink-0 rounded-sm border border-black/10"
      style={hatch ? { background: `repeating-linear-gradient(135deg, ${color} 0 1.5px, transparent 1.5px 4px)`, borderColor: color } : { background: color }}
    />
  );
}

function LegendBlock({ title, items }: { title: string; items: { label: string; color: string; hatch?: boolean }[] }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</div>
      <ul className="space-y-1 text-xs">
        {items.map((c) => (
          <li key={c.label} className="flex items-center gap-2"><Swatch color={c.color} hatch={c.hatch} />{c.label}</li>
        ))}
      </ul>
    </div>
  );
}

/** Legend for the active colour mode and enabled overlays. */
export function Legend({
  layers,
  hasBuildings,
  constraintDatasets,
  landuseClasses,
  useShares = [],
}: {
  layers: LayerState;
  hasBuildings: boolean;
  constraintDatasets: string[];
  landuseClasses: string[];
  useShares?: { id: UseSource; share: number }[];
}) {
  const blocks: React.ReactNode[] = [];
  if (hasBuildings) {
    const ml = modeLegend(layers.mode);
    if (ml) blocks.push(<LegendBlock key="m" title={ml.title} items={ml.items} />);
    if (layers.mode === "type") {
      if (useShares.length)
        blocks.push(
          <p key="ms" className="text-[11px] leading-snug text-muted">
            Type from {useShares.map((u) => `${USE_SOURCE_LABELS[u.id]} ${Math.round(u.share * 100)}%`).join(" · ")}.
            Ground-floor businesses describe the ground floor only.
          </p>,
        );
    }
  }
  if (layers.overlays.landuse && landuseClasses.length)
    blocks.push(<LegendBlock key="l" title="Land use" items={landuseClasses.map((c) => ({ label: LANDUSE_LABELS[c] ?? c, color: LANDUSE_COLOURS[c] ?? LANDUSE_COLOURS.other }))} />);
  if (layers.overlays.streets) blocks.push(<LegendBlock key="s" title="Streets" items={STREET_CLASSES} />);
  if (layers.overlays.constraints) {
    const sets = constraintDatasets.length ? constraintDatasets : [];
    blocks.push(
      sets.length ? (
        <LegendBlock key="c" title="Planning constraints" items={sets.map((d) => { const st = CONSTRAINT_STYLES[d] ?? CONSTRAINT_OTHER; return { label: CONSTRAINT_STYLES[d] ? st.label : d, color: st.color, hatch: true }; })} />
      ) : (
        <p key="c" className="text-[11px] text-muted">No planning constraints here (data covers Great Britain only).</p>
      ),
    );
  }
  if (!blocks.length) return null;
  return <div className="space-y-2.5">{blocks}</div>;
}

export function LayersControl({
  layers,
  onChange,
  legend,
}: {
  layers: LayerState;
  onChange: (l: LayerState) => void;
  legend: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const setMode = (mode: ColourMode) => onChange({ ...layers, mode });
  const toggle = (o: Overlay) => onChange({ ...layers, overlays: { ...layers.overlays, [o]: !layers.overlays[o] } });
  const active = OVERLAYS.filter((o) => layers.overlays[o.id]).length;

  // The desktop panel and the mobile sheet both render this body. Radios need a
  // distinct group name per copy: one name across both lets the hidden copy hold
  // the checked state, so the visible radios look unselected.
  const uid = useId();
  const body = (copy: "desktop" | "mobile") => (
    <div className="space-y-3 text-xs">
      <fieldset>
        <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Colour buildings by</legend>
        <div className="space-y-0.5">
          {MODES.map((m) => (
            <label key={m.id} className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-track">
              <input type="radio" name={`colour-mode-${uid}-${copy}`} className="accent-[var(--accent)]" checked={layers.mode === m.id} onChange={() => setMode(m.id)} />
              {m.label}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Overlays</legend>
        <div className="space-y-0.5">
          {OVERLAYS.map((o) => (
            <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-track">
              <input type="checkbox" className="accent-[var(--accent)]" checked={layers.overlays[o.id]} onChange={() => toggle(o.id)} />
              {o.label}
              <span className="ml-auto text-[10px] text-muted">{o.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  );

  return (
    <>
      {/* desktop: inline glass panel */}
      <div className="pointer-events-auto glass hidden rounded-xl sm:block">
        <button className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <span aria-hidden>▦</span> Layers
          {active > 0 && <span className="rounded-full bg-accent px-1.5 text-[10px] text-accent-fg">{active}</span>}
          <span className="ml-auto" aria-hidden>{open ? "▾" : "▸"}</span>
        </button>
        {open && <div className="border-t border-line px-3 pb-3 pt-2">{body("desktop")}</div>}
        {!!legend && <div className="border-t border-line px-3 py-2.5 empty:hidden">{legend}</div>}
      </div>

      {/* mobile: button + bottom sheet */}
      <div className="pointer-events-auto sm:hidden">
        <button className="glass flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-semibold" aria-expanded={open} onClick={() => setOpen(true)}>
          <span aria-hidden>▦</span> Layers
          {active > 0 && <span className="rounded-full bg-accent px-1.5 text-[10px] text-accent-fg">{active}</span>}
        </button>
        {open && (
          <div className="glass fixed inset-x-0 bottom-0 z-30 max-h-[70vh] overflow-y-auto rounded-t-2xl p-4" role="dialog" aria-label="Map layers">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Layers</h2>
              <button className="rounded-lg px-2 py-1 text-xs hover:bg-track" onClick={() => setOpen(false)}>Done</button>
            </div>
            {body("mobile")}
            {!!legend && <div className="mt-3 border-t border-line pt-3 empty:hidden">{legend}</div>}
          </div>
        )}
      </div>
    </>
  );
}
