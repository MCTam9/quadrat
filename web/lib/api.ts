import type { Analysis, Climate, LayerEvent, Preview, ReadyEvent } from "./types";

export type TokenGetter = () => Promise<string | null>;

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function post(path: string, body: unknown, getToken: TokenGetter, signal?: AbortSignal, accept?: string) {
  const token = await getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (accept) headers.Accept = accept;
  const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body), signal });
  return res;
}

async function errorFrom(res: Response): Promise<ApiError> {
  let msg = `${res.status} ${res.statusText}`;
  try {
    const j = await res.clone().json();
    if (j?.error) msg = String(j.error);
    else if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* not json */
  }
  return new ApiError(msg, res.status);
}

export interface SseMessage {
  event: string;
  data: string;
}

/** Incremental SSE parser: feed text chunks, get complete messages. */
export function createSseParser(onMessage: (m: SseMessage) => void) {
  let buf = "";
  return (chunk: string) => {
    buf += chunk.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue;
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length) onMessage({ event, data: data.join("\n") });
    }
  };
}

export async function loadSite(
  lon: number,
  lat: number,
  halfWidthM: number,
  getToken: TokenGetter,
  onLayer: (l: LayerEvent) => void,
  signal?: AbortSignal,
): Promise<ReadyEvent> {
  const res = await post("/api/load", { lon, lat, half_width_m: halfWidthM }, getToken, signal, "text/event-stream");
  if (!res.ok || !res.body) throw await errorFrom(res);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let ready: ReadyEvent | null = null;
  let failure: string | null = null;
  const feed = createSseParser((m) => {
    try {
      const d = JSON.parse(m.data);
      if (m.event === "layer") onLayer(d as LayerEvent);
      else if (m.event === "ready") ready = d as ReadyEvent;
      else if (m.event === "error") failure = String(d.error ?? "load failed");
    } catch {
      /* ignore malformed event */
    }
  });
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    feed(dec.decode(value, { stream: true }));
  }
  if (failure) throw new ApiError(failure, 500);
  if (!ready) throw new ApiError("Load ended without a ready event", 502);
  return ready;
}

export interface SiteParams {
  site_id: string;
  lon: number;
  lat: number;
  half_width_m: number;
}

export class ReloadRequired extends Error {}

async function json<T>(path: string, body: unknown, getToken: TokenGetter, signal?: AbortSignal): Promise<T> {
  const res = await post(path, body, getToken, signal);
  if (res.status === 409) throw new ReloadRequired();
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

export const analyse = (p: SiteParams, t: TokenGetter, s?: AbortSignal) => json<Analysis>("/api/analyse", p, t, s);
export const preview = (p: SiteParams, t: TokenGetter, s?: AbortSignal) => json<Preview>("/api/preview", p, t, s);

export const climate = (siteId: string, t: TokenGetter, s?: AbortSignal) =>
  json<Climate>("/api/climate", { site_id: siteId }, t, s);

export async function exportZip(
  p: SiteParams & { formats: string[]; report: boolean },
  getToken: TokenGetter,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await post("/api/export", p, getToken, signal);
  if (!res.ok) throw await errorFrom(res);
  return res.blob();
}
