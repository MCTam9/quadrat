import { useSyncExternalStore } from "react";

const QUERY = "(prefers-color-scheme: dark)";

export function prefersDark(): boolean {
  return typeof matchMedia === "function" && matchMedia(QUERY).matches;
}

function subscribe(cb: () => void) {
  const m = matchMedia(QUERY);
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
}

/** Follows the OS colour scheme live; false on the server. */
export function useDark(): boolean {
  return useSyncExternalStore(subscribe, prefersDark, () => false);
}
