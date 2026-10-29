import { describe, expect, it } from 'vitest';
import type { Device, RackPort } from '@/types';
import {
  MAX_UNIT_PX,
  MIN_UNIT_PX,
  assignLanes,
  channelPath,
  faceLayout,
  faceTop,
  freeRuns,
  isShortCable,
  loopPath,
  rackFrame,
  snapUnit,
  unitTop,
} from './rackGeometry';
import { deviceEntry } from './rackModel';

const ports = (count: number, kind = 'RJ45'): RackPort[] =>
  Array.from({ length: count }, (_, i) => ({ id: 100 + i, device_id: 1, rack_item_id: null, number: i + 1, kind, side: 'front' }));

describe('rack frame', () => {
  it('makes units as tall as the height allows, within limits', () => {
    expect(rackFrame(42, 19, { width: 900, height: 1000 }).unitPx).toBe(23);
    expect(rackFrame(42, 19, { width: 900, height: 300 }).unitPx).toBe(MIN_UNIT_PX);
    expect(rackFrame(4, 19, { width: 900, height: 1000 }).unitPx).toBe(MAX_UNIT_PX);
  });

  it('draws a 10-inch rack narrower than a 19-inch one', () => {
    const full = rackFrame(12, 19, { width: 800, height: 600 });
    const half = rackFrame(12, 10, { width: 800, height: 600 });
    expect(half.facePx).toBeLessThan(full.facePx * 0.7);
  });

  it('draws every unit at full height in detail mode, whatever the box', () => {
    expect(rackFrame(42, 19, { width: 900, height: 300 }, true).unitPx).toBe(MAX_UNIT_PX);
  });

  it('fits a 19-inch rack into a phone', () => {
    const phone = rackFrame(42, 19, { width: 343, height: 600 });
    expect(phone.railPx + phone.facePx + phone.channelPx).toBeLessThanOrEqual(343);
  });

  it('counts units from the bottom and snaps a faceplate to the nearest unit', () => {
    const f = rackFrame(10, 19, { width: 800, height: 260 });
    expect(unitTop(f, 10)).toBe(f.padPx);
    expect(unitTop(f, 1)).toBe(f.padPx + 9 * f.unitPx);
    expect(snapUnit(f, faceTop(f, 7))).toBe(7);
    expect(snapUnit(f, faceTop(f, 7) + f.unitPx * 0.4)).toBe(7);
    expect(snapUnit(f, faceTop(f, 7) + f.unitPx * 0.6)).toBe(6);
  });
});

describe('faceplate layout', () => {
  it('right-aligns the jacks and leaves the label room on the left', () => {
    const layout = faceLayout(ports(8), 400, 22);
    expect(layout.jacks).toHaveLength(8);
    const last = layout.jacks[7];
    expect(last.x + last.w).toBeLessThanOrEqual(400 - layout.earPx - 8);
    expect(layout.jackLeft).toBeGreaterThan(layout.earPx + 100);
    expect(layout.twoLines).toBe(false);
  });

  it('puts 48 ports in two rows with odd ports on top and a gap after twelve columns', () => {
    const layout = faceLayout(ports(48), 420, 22);
    const [p1, p2, p3] = layout.jacks;
    expect(p1.x).toBe(p2.x);
    expect(p1.y).toBeLessThan(p2.y);
    expect(p3.y).toBe(p1.y);
    const pitch = p3.x - p1.x;
    const p23 = layout.jacks[22];
    const p25 = layout.jacks[24];
    expect(p25.x - p23.x).toBeGreaterThan(pitch * 1.4);
    // Everything stays inside the faceplate
    for (const jack of layout.jacks) expect(jack.y + jack.h).toBeLessThanOrEqual(22);
  });

  it('draws SFP cages wide and flat, LC narrow and tall', () => {
    const sfp = faceLayout(ports(4, 'SFP+'), 420, 22).jacks[0];
    const lc = faceLayout(ports(4, 'LC'), 420, 22).jacks[0];
    expect(sfp.w).toBeGreaterThan(sfp.h);
    expect(lc.h).toBeGreaterThan(lc.w);
  });

  it('has nothing to draw without ports', () => {
    expect(faceLayout([], 400, 40)).toMatchObject({ jacks: [], twoLines: true });
  });
});

describe('cables', () => {
  it('hangs a short cable as a loop and sends a long one through the channel', () => {
    const f = rackFrame(10, 19, { width: 800, height: 260 });
    expect(isShortCable(f, { x: 0, y: 10 }, { x: 0, y: 10 + f.unitPx * 2 })).toBe(true);
    expect(isShortCable(f, { x: 0, y: 10 }, { x: 0, y: 10 + f.unitPx * 4 })).toBe(false);
    expect(loopPath({ x: 10, y: 20 }, { x: 30, y: 44 }, 14)).toBe('M 10 20 C 14 34 34 58 30 44');
    const path = channelPath({ x: 10, y: 20 }, { x: 30, y: 120 }, 300);
    expect(path.startsWith('M 10 20 C 155 20 300 20 300 34')).toBe(true);
    expect(path.endsWith('300 120 165 120 30 120')).toBe(true);
  });

  it('gives overlapping runs their own lane and lets separate runs share one', () => {
    const lanes = assignLanes(
      [
        { id: 1, top: 0, bottom: 100 },
        { id: 2, top: 50, bottom: 150 },
        { id: 3, top: 200, bottom: 260 },
      ],
      4,
    );
    expect(lanes.get(1)).not.toBe(lanes.get(2));
    expect(lanes.get(3)).toBe(0);
  });
});

describe('free space', () => {
  it('sums free units into runs, top first', () => {
    const at = (id: number, unit: number | null, height = 1) => deviceEntry({ id, ip: '10.0.0.1', rack_unit: unit, rack_height: height } as Device, 'x');
    expect(freeRuns(8, [at(1, 7, 2), at(2, 3), at(3, null)])).toEqual([
      { top: 8, length: 1 },
      { top: 5, length: 2 },
      { top: 2, length: 2 },
    ]);
    // The entry being dragged leaves its place free
    expect(freeRuns(4, [at(1, 4, 4)], 'device-1')).toEqual([{ top: 4, length: 4 }]);
  });
});
