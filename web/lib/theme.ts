import { useSyncExternalStore } from "react";
import { QUERY, THEME_KEY } from "./theme-boot";

/** The viewer's choice: follow the OS, or pin light or dark. Kept per browser in localStorage. */
export type ThemePref = "system" | "light" | "dark";
export const THEME_PREFS: { id: ThemePref; label: string }[] = [
  { id: "system", label: "Auto" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];
const EVENT = "quadrat-theme";

export function themePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    /* storage blocked: follow the OS */
  }
  return "system";
}

export function resolveDark(pref: ThemePref, osDark: boolean): boolean {
  return pref === "system" ? osDark : pref === "dark";
}

/** True when the page is dark right now, whether chosen or inherited from the OS. */
export function prefersDark(): boolean {
  const os = typeof matchMedia === "function" && matchMedia(QUERY).matches;
  return typeof window !== "undefined" && resolveDark(themePref(), os);
}

/** CSS keys every colour on `html[data-theme]`; the inline script in layout.tsx sets it before paint. */
function apply() {
  document.documentElement.dataset.theme = prefersDark() ? "dark" : "light";
}

export function setThemePref(pref: ThemePref) {
  try {
    if (pref === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* storage blocked: the choice lasts for this page only */
  }
  apply();
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void) {
  const m = matchMedia(QUERY);
  const onOs = () => {
    apply();
    cb();
  };
  m.addEventListener("change", onOs);
  window.addEventListener(EVENT, cb);
  return () => {
    m.removeEventListener("change", onOs);
    window.removeEventListener(EVENT, cb);
  };
}

/** Dark or not, live: follows the viewer's choice, else the OS. False on the server. */
export function useDark(): boolean {
  return useSyncExternalStore(subscribe, prefersDark, () => false);
}

/** The viewer's choice, live. */
export function useThemePref(): ThemePref {
  return useSyncExternalStore(subscribe, themePref, () => "system");
}
