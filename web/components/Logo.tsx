/** Quadrat mark: a 3 x 3 grid of white squares on a black tile (the favicon, drawn as vector). */
export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  const cells = [3, 13, 23];
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#000" />
      {cells.flatMap((y) => cells.map((x) => <rect key={`${x},${y}`} x={x} y={y} width="6" height="6" fill="#fff" />))}
    </svg>
  );
}
