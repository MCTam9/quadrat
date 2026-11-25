import { describe, expect, it } from "vitest";
import { downloadLabel, fileCount } from "./export";

describe("downloadLabel", () => {
  it("counts formats plus the PDF", () => {
    expect(fileCount(["dxf", "geojson"], true)).toBe(3);
    expect(downloadLabel(["dxf", "geojson"], true)).toBe("Download 3 files");
    expect(downloadLabel(["dxf"], false)).toBe("Download 1 file");
    expect(downloadLabel([], true)).toBe("Download 1 file");
    expect(downloadLabel([], false)).toBe("Choose files to download");
  });
});
