/**
 * Placing without a mouse drag: a tray entry is picked first (click, Enter or Space) and then put on a free
 * unit (click or Enter). These helpers say which units take the picked entry and how the arrow keys walk them.
 */
import { fitsAt, type RackEntry } from './rackModel';

/** Top units where `entry` fits, top first; the same check a drop uses. */
export function placeTargets(units: number, entries: RackEntry[], entry: RackEntry): number[] {
  const targets: number[] = [];
  for (let unit = units; unit >= 1; unit--) {
    if (fitsAt(units, entries, unit, entry.height, entry.key)) targets.push(unit);
  }
  return targets;
}

/**
 * The target the arrow keys go to from `unit`: `down` is the next lower unit, `up` the next higher one.
 * Stays put at either end of the rack; a unit that is no target starts from the nearest one in that direction.
 */
export function stepTarget(targets: number[], unit: number, direction: 'up' | 'down'): number | null {
  if (targets.length === 0) return null;
  const next = direction === 'down' ? targets.find((u) => u < unit) : [...targets].reverse().find((u) => u > unit);
  return next ?? (targets.includes(unit) ? unit : null);
}
