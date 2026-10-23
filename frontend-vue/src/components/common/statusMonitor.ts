/**
 * Slot model behind StatusMonitor.vue.
 *
 * Adapted from the Status Monitor block of 8starlabs-ui (https://github.com/8starlabs/ui),
 * MIT License, Copyright (c) 2025 Tham Kei Lok. See THIRD_PARTY_NOTICES.md.
 */

export type SlotStatus = 'normal' | 'warning' | 'error' | 'empty';

export interface StatusSlot {
  status: SlotStatus;
  /** Availability of the slot in percent, null when nothing was measured */
  pct: number | null;
  start: Date;
  end: Date;
}

/** Full at or above `upAt`, partial above 0, down at 0; null or negative means no data. */
export function slotStatus(pct: number | null | undefined, upAt = 99): SlotStatus {
  if (pct === null || pct === undefined || pct < 0) return 'empty';
  if (pct >= upAt) return 'normal';
  return pct > 0 ? 'warning' : 'error';
}

/** Splits the window that ends at `end` into one slot per value, oldest first. */
export function buildSlots(values: (number | null)[], spanHours: number, end: Date, upAt = 99): StatusSlot[] {
  const slotMs = (spanHours * 3_600_000) / Math.max(1, values.length);
  const startMs = end.getTime() - spanHours * 3_600_000;
  return values.map((raw, i) => {
    const pct = raw === null || raw === undefined || raw < 0 ? null : raw;
    return {
      status: slotStatus(pct, upAt),
      pct,
      start: new Date(startMs + i * slotMs),
      end: new Date(startMs + (i + 1) * slotMs),
    };
  });
}

/** How many of the newest slots fit into `width` pixels, keeping each bar at least `minBar` wide. */
export function fitSlots(count: number, width: number, minBar = 3, gap = 2): number {
  if (width <= 0) return count;
  return Math.max(1, Math.min(count, Math.floor((width + gap) / (minBar + gap))));
}
