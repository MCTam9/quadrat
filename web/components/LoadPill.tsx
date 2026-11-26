"use client";

/** Small status pill over the map while layers are still loading; renders nothing once all have arrived. */
export function LoadPill({ pending }: { pending: string[] }) {
  return (
    <div
      className="pointer-events-none absolute inset-x-3 bottom-[calc(var(--peek)+4rem)] z-10 flex justify-center sm:bottom-16 sm:right-[26rem]"
      role="status"
      aria-live="polite"
    >
      {pending.length > 0 && (
        <span className="sheet px-3 py-1 text-xs">
          Loading: {pending.map((l) => l.toLowerCase()).join(", ")}…
        </span>
      )}
    </div>
  );
}
