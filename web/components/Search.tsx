"use client";

import { useEffect, useRef, useState } from "react";
import { parseCoordinates } from "@/lib/coords";

interface Hit {
  label: string;
  lon: number;
  lat: number;
}

interface Props {
  onPick: (lon: number, lat: number) => void;
}

function label(p: Record<string, string | undefined>): string {
  const parts = [p.name, p.street, p.city || p.district, p.state, p.country].filter(Boolean);
  return Array.from(new Set(parts)).join(", ");
}

export function Search({ onPick }: Props) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ctl = useRef<AbortController | null>(null);
  // The query text a pick wrote into the box; searching it again would reopen the list.
  const picked = useRef<string | null>(null);

  useEffect(() => {
    const text = q.trim();
    if (text.length < 3 || parseCoordinates(text) || q === picked.current) return;
    const t = setTimeout(async () => {
      ctl.current?.abort();
      const c = new AbortController();
      ctl.current = c;
      setBusy(true);
      setErr(null);
      try {
        const res = await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(text)}&limit=6`, { signal: c.signal });
        if (!res.ok) throw new Error(`Search failed (${res.status})`);
        const j = (await res.json()) as { features: { geometry: { coordinates: [number, number] }; properties: Record<string, string> }[] };
        setHits(j.features.map((f) => ({ label: label(f.properties), lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] })));
        setOpen(true);
        setActive(-1);
        setBusy(false);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setErr((e as Error).message);
        setBusy(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  function choose(h: Hit) {
    ctl.current?.abort();
    picked.current = h.label;
    setQ(h.label);
    setOpen(false);
    setActive(-1);
    (document.activeElement as HTMLElement | null)?.blur();
    onPick(h.lon, h.lat);
  }

  function submit() {
    const c = parseCoordinates(q);
    if (c) {
      setOpen(false);
      (document.activeElement as HTMLElement | null)?.blur();
      onPick(c.lon, c.lat);
    } else if (active >= 0 && hits[active]) choose(hits[active]);
    else if (hits[0]) choose(hits[0]);
  }

  const coord = parseCoordinates(q);
  const shown = q.trim().length >= 3 && !coord ? hits : [];

  return (
    <div className="relative">
      <div className="sheet flex items-center gap-2 px-3 py-2 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ink">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-graphite" aria-hidden>
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          role="combobox"
          aria-expanded={open && shown.length > 0}
          aria-controls="search-results"
          aria-label="Search a place or paste coordinates"
          className="w-full bg-transparent text-sm outline-none placeholder:text-graphite"
          placeholder="Search a place or paste lat, lon"
          value={q}
          onChange={(e) => {
            picked.current = null;
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(q !== picked.current)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(shown.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(-1, a - 1));
            } else if (e.key === "Enter") submit();
            else if (e.key === "Escape") setOpen(false);
          }}
        />
        {busy && <span className="skeleton h-3 w-3 shrink-0" aria-label="Searching" />}
      </div>
      {coord && open && (
        <button
          className="sheet mt-1 w-full px-3 py-2 text-left text-sm hover:bg-hover"
          onClick={() => submit()}
        >
          Go to {coord.lat.toFixed(5)}, {coord.lon.toFixed(5)}
        </button>
      )}
      {err && <p className="sheet mt-1 px-3 py-2 text-xs">{err}</p>}
      {open && shown.length > 0 && (
        <ul id="search-results" role="listbox" className="sheet mt-1 max-h-72 overflow-auto py-1">
          {shown.map((h, i) => (
            <li key={`${h.lon},${h.lat},${i}`} role="option" aria-selected={i === active}>
              <button
                className={`w-full px-3 py-2 text-left text-sm hover:bg-hover ${i === active ? "bg-hover" : ""}`}
                onClick={() => choose(h)}
              >
                {h.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
