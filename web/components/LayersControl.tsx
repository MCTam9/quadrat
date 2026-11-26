"use client";

import { useId, useState } from "react";
import {
  CONSTRAINT_OTHER,
  CONSTRAINT_STYLES,
  LANDUSE_COLOURS,
  LANDUSE_LABELS,
  MODES,
  modeLegend,
  OVERLAYS,
  palette,
  sentenceCase,
  RED_LINE,
  STREET_CLASSES,
  USE_SOURCE_LABELS,
  type ColourMode,
  type LayerState,
  type Overlay,
  type UseSource,
} from "@/lib/layers";
import { setThemePref, THEME_PREFS, useDark, useThemePref, type ThemePref } from "@/lib/theme";

function Swatch({ color, hatch, line }: { color: string; hatch?: boolean; line?: boolean }) {
  if (line) return <span className="h-0 w-3 shrink-0 border-t-2" style={{ borderColor: color }} aria-hidden />;
  return (
    <span
      className="h-3 w-3 shrink-0 border border-rule"
      style={hatch ? { background: `repeating-linear-gradient(135deg, ${color} 0 1.5px, transparent 1.5px 4px)`, borderColor: color } : { background: color }}
      aria-hidden
    />
  );
}

type Item = { label: string; color: string; hatch?: boolean; line?: boolean };

function LegendBlock({ title, items }: { title: string; items: Item[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-semibold">{title}</div>
      <ul className="space-y-1 text-xs">
        {items.map((c) => (
          <li key={c.label} className="flex items-center gap-2">
            <Swatch color={c.color} hatch={c.hatch} line={c.line} />
            {c.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Legend for the active colour mode and enabled overlays: its own small card, bottom-left. */
export function LegendCard({
  layers,
  hasBuildings,
  hasContext,
  constraintDatasets,
  landuseClasses,
  useShares = [],
}: {
  layers: LayerState;
  hasBuildings: boolean;
  hasContext: boolean;
  constraintDatasets: string[];
  landuseClasses: string[];
  useShares?: { id: UseSource; share: number }[];
}) {
  const dark = useDark();
  const pal = palette(dark);
  const bodyId = useId();
  // Phones start with the legend folded so it does not cover a third of the map. The legend
  // only mounts after the preview loads, so it never renders on the server.
  const [open, setOpen] = useState(() => typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches);
  const blocks: React.ReactNode[] = [];
  if (hasBuildings) {
    const ml = modeLegend(layers.mode, dark);
    if (ml) blocks.push(<LegendBlock key="m" title={ml.title} items={ml.items} />);
    else {
      const items: Item[] = [{ label: "Site buildings", color: pal.ink }];
      if (hasContext) items.push({ label: "Context buildings", color: pal.context });
      blocks.push(<LegendBlock key="m" title="Buildings" items={items} />);
    }
    if (layers.mode === "type" && useShares.length)
      blocks.push(
        <p key="ms" className="text-xs leading-snug text-graphite">
          Type from {useShares.map((u) => `${USE_SOURCE_LABELS[u.id]} ${Math.round(u.share * 100)} %`).join(", ")}. Ground-floor businesses describe the ground floor only.
        </p>,
      );
  }
  if (layers.overlays.landuse && landuseClasses.length)
    blocks.push(<LegendBlock key="l" title="Land use" items={landuseClasses.map((c) => ({ label: LANDUSE_LABELS[c] ?? c, color: LANDUSE_COLOURS[c] ?? LANDUSE_COLOURS.other }))} />);
  if (layers.overlays.streets)
    blocks.push(<LegendBlock key="s" title="Streets" items={STREET_CLASSES.map((c) => ({ label: c.label, color: dark ? c.colorDark : c.color, line: true }))} />);
  if (layers.overlays.constraints)
    blocks.push(
      constraintDatasets.length ? (
        <LegendBlock
          key="c"
          title="Planning constraints"
          items={constraintDatasets.map((d) => {
            const st = CONSTRAINT_STYLES[d] ?? CONSTRAINT_OTHER;
            return { label: CONSTRAINT_STYLES[d] ? st.label : sentenceCase(d), color: dark ? st.colorDark : st.color, hatch: true };
          })}
        />
      ) : (
        <p key="c" className="text-xs text-graphite">No planning constraints here (data covers Great Britain only).</p>
      ),
    );
  blocks.push(<LegendBlock key="site" title="Site" items={[{ label: "Site boundary", color: RED_LINE, line: true }]} />);
  return (
    <section className="sheet pointer-events-auto w-56" aria-label="Legend">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold sm:hidden"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
      >
        Legend <Chevron open={open} />
      </button>
      <div id={bodyId} className={`${open ? "block" : "hidden"} max-h-[32dvh] space-y-2.5 overflow-y-auto p-3 pt-0 sm:block sm:pt-3`}>
        {blocks}
      </div>
    </section>
  );
}

const Chevron = ({ open }: { open: boolean }) => (
  <svg className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
    <path d="M2 4.5 6 8.5 10 4.5" />
  </svg>
);

/** Sun for light, moon for dark, half-and-half for following the OS. */
function ThemeIcon({ pref }: { pref: ThemePref }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.5">
      {pref === "light" && (
        <>
          <circle cx="8" cy="8" r="3" />
          <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6 13 13M3 13l1.4-1.4M11.6 4.4 13 3" />
        </>
      )}
      {pref === "dark" && <path d="M13.5 9.5A5.5 5.5 0 1 1 6.5 2.5a4.5 4.5 0 0 0 7 7Z" />}
      {pref === "system" && (
        <>
          <circle cx="8" cy="8" r="5.5" />
          <path d="M8 2.5a5.5 5.5 0 0 1 0 11Z" fill="currentColor" />
        </>
      )}
    </svg>
  );
}

/** Cycles Auto (follow the OS), Light and Dark. */
function ThemeButton() {
  const pref = useThemePref();
  const i = THEME_PREFS.findIndex((p) => p.id === pref);
  const next = THEME_PREFS[(i + 1) % THEME_PREFS.length];
  const label = THEME_PREFS[i].label;
  return (
    <button
      type="button"
      className="sheet flex items-center gap-1.5 px-2.5 py-2 text-xs font-semibold hover:bg-hover"
      title={`Theme: ${label}. Click for ${next.label.toLowerCase()}.`}
      aria-label={`Theme: ${label}. Switch to ${next.label.toLowerCase()}`}
      onClick={() => setThemePref(next.id)}
    >
      <ThemeIcon pref={pref} />
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

/** 2D/3D and the layers menu in one compact row. The menu scrolls inside its own max height. */
export function LayersControl({
  layers,
  onChange,
  threeD,
  onThreeD,
}: {
  layers: LayerState;
  onChange: (l: LayerState) => void;
  threeD: boolean;
  onThreeD: (v: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const uid = useId();
  const panelId = `${uid}-layers`;
  const setMode = (mode: ColourMode) => onChange({ ...layers, mode });
  const toggle = (o: Overlay) => onChange({ ...layers, overlays: { ...layers.overlays, [o]: !layers.overlays[o] } });
  const active = OVERLAYS.filter((o) => layers.overlays[o.id]).length;
  const modeLabel = MODES.find((m) => m.id === layers.mode)?.label ?? "";

  return (
    <div className="pointer-events-auto">
      <div className="flex items-stretch gap-2">
        <div className="sheet flex" role="group" aria-label="View mode">
          {[false, true].map((v) => (
            <button
              key={String(v)}
              aria-pressed={threeD === v}
              onClick={() => onThreeD(v)}
              className={`px-3 py-2 text-xs font-semibold ${threeD === v ? "bg-ink text-sheet" : "hover:bg-hover"}`}
            >
              {v ? "3D" : "2D"}
            </button>
          ))}
        </div>
        <button
          className="sheet flex flex-1 items-center gap-2 px-3 py-2 text-left text-xs font-semibold hover:bg-hover"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((o) => !o)}
        >
          Layers
          <span className="truncate font-normal text-graphite">
            {modeLabel}
            {active > 0 ? `, ${active} on` : ""}
          </span>
          <span className="ml-auto"><Chevron open={open} /></span>
        </button>
        <ThemeButton />
      </div>
      {open && (
        <div id={panelId} className="sheet mt-2 max-h-[min(44dvh,24rem)] space-y-3 overflow-y-auto p-3 text-xs">
          <fieldset>
            <legend className="mb-1 font-semibold">Colour buildings by</legend>
            <div className="space-y-0.5">
              {MODES.map((m) => (
                <label key={m.id} className="flex cursor-pointer items-center gap-2 px-1 py-1.5 hover:bg-hover">
                  <input type="radio" name={`${uid}-mode`} checked={layers.mode === m.id} onChange={() => setMode(m.id)} />
                  {m.label}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-1 font-semibold">Overlays</legend>
            <div className="space-y-0.5">
              {OVERLAYS.map((o) => (
                <label key={o.id} className="flex cursor-pointer items-center gap-2 px-1 py-1.5 hover:bg-hover">
                  <input type="checkbox" checked={layers.overlays[o.id]} onChange={() => toggle(o.id)} />
                  {o.label}
                  <span className="ml-auto text-graphite">{o.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>
        </div>
      )}
    </div>
  );
}
