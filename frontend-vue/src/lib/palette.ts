/**
 * The line palette (--line-1 … --line-10 in index.css, its own set for light and dark) as concrete colours, for
 * pickers that store a colour as #rrggbb: line colours, link type colours and the colours of address areas.
 */
const HEX = /^#[0-9a-f]{6}$/i;
const LINE_SLOTS = 10;

/** The palette of the current theme as #rrggbb; slots that are not plain hex are left out. */
export function linePaletteHex(root: Element = document.documentElement): string[] {
  const style = getComputedStyle(root);
  return Array.from({ length: LINE_SLOTS }, (_, i) => style.getPropertyValue(`--line-${i + 1}`).trim()).filter((c) => HEX.test(c));
}

/**
 * A colour for one more thing next to those using `used`: the first palette colour nobody uses yet, else the
 * palette again from the start. Empty when there is no palette (no stylesheet).
 */
export function nextPaletteColour(used: string[], palette: string[]): string {
  if (palette.length === 0) return '';
  const taken = new Set(used.map((c) => c.toLowerCase()));
  return palette.find((c) => !taken.has(c.toLowerCase())) ?? palette[used.length % palette.length];
}
