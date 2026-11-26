// Server-safe: imported by app/layout.tsx, so no React client hooks here.
export const THEME_KEY = "quadrat-theme";
export const QUERY = "(prefers-color-scheme: dark)";

/** Runs before first paint (inlined in <head>) so a pinned theme never flashes the other one. */
export const THEME_BOOT = `try{var p=localStorage.getItem("${THEME_KEY}"),d=p==="dark"||(p!=="light"&&matchMedia("${QUERY}").matches);document.documentElement.dataset.theme=d?"dark":"light"}catch(e){}`;
