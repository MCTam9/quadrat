/** Number of files in the bundle: one per selected format, plus the PDF report. */
export function fileCount(formats: readonly string[], report: boolean): number {
  return formats.length + (report ? 1 : 0);
}

/** Label for the download button, e.g. "Download 3 files". */
export function downloadLabel(formats: readonly string[], report: boolean): string {
  const n = fileCount(formats, report);
  return n === 0 ? "Choose files to download" : `Download ${n} ${n === 1 ? "file" : "files"}`;
}
