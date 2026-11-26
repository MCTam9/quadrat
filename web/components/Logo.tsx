/** Quadrat mark: a white 3 x 3 quadrat frame (four lines each way) on a black tile. Same as the favicon. */
export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  const lines = [3, 11, 19, 27]; // 2-unit lines, 6-unit cells, on a 32-unit grid
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#000" />
      <g fill="#fff">
        {lines.map((p) => (
          <g key={p}>
            <rect x={p} y={3} width={2} height={26} />
            <rect x={3} y={p} width={26} height={2} />
          </g>
        ))}
      </g>
    </svg>
  );
}
