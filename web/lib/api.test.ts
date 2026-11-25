import { describe, expect, it } from "vitest";
import { createSseParser } from "./api";

describe("sse parser", () => {
  it("handles split chunks and multiple events", () => {
    const out: string[] = [];
    const feed = createSseParser((m) => out.push(`${m.event}:${m.data}`));
    feed('event: layer\ndata: {"a":1}\n');
    feed('\nevent: ready\r\ndata: {"b":2}\r\n\r\n: ping\n\n');
    expect(out).toEqual(['layer:{"a":1}', 'ready:{"b":2}']);
  });
});
