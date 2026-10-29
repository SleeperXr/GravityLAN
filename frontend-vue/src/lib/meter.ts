/**
 * Progress and meter fills move with `transform` only, so a changing value animates on the compositor instead of
 * relaying out the bar on every frame. A rounded fill slides in from the left (its rounded end stays round, the
 * track clips the rest); a square fill scales from its left edge.
 */

const clampPercent = (percent: number): number => Math.min(100, Math.max(0, Number.isFinite(percent) ? percent : 0));

/** Transform that shows `percent` of a full-width rounded fill: shifted left by the part that is not filled. */
export function fillShift(percent: number): string {
  return `translateX(${clampPercent(percent) - 100}%)`;
}

/** Transform that shows `percent` of a full-width square fill, scaled from its left edge. */
export function fillScale(percent: number): string {
  return `scaleX(${clampPercent(percent) / 100})`;
}

/**
 * Layers for a bar of several segments side by side. Each segment becomes a full-width layer scaled to where it
 * ends, drawn bottom first, so the earlier segments cover the later ones and each shows only its own part.
 */
export function stackedLayers<T extends { value: number }>(segments: T[], total: number): (T & { transform: string })[] {
  let end = 0;
  const layers = segments.map((segment) => {
    end += total > 0 ? (segment.value / total) * 100 : 0;
    return { ...segment, transform: fillScale(end) };
  });
  return layers.reverse();
}
