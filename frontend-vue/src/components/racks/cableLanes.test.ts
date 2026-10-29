import { describe, expect, it } from 'vitest';
import type { RackPort } from '@/types';
import { CHANNEL_PX, LANE_PX, channelWidth, laneCount, laneX } from './cableLanes';

const port = (id: number, side: 'front' | 'rear') => ({ id, device_id: 1, rack_item_id: null, number: id, kind: 'RJ45', side }) as RackPort;
const cable = (a: number, b: number) => ({ a_port_id: a, b_port_id: b });

describe('cable lanes', () => {
  it('gives each cable with both jacks on the shown side a lane of its own', () => {
    const ports = new Map([1, 2, 3, 4].map((id) => [id, port(id, id === 4 ? 'rear' : 'front')]));
    const cables = [cable(1, 2), cable(2, 3), cable(3, 4), cable(1, 99)];
    expect(laneCount(cables, ports, 'front')).toBe(2);
    expect(laneCount(cables, ports, 'rear')).toBe(0);
  });

  it('keeps the usual channel up to eight cables and widens it beyond', () => {
    expect(channelWidth(0)).toBe(CHANNEL_PX);
    expect(channelWidth(8)).toBe(CHANNEL_PX);
    expect(channelWidth(9)).toBe(CHANNEL_PX + LANE_PX);
    expect(channelWidth(20)).toBe(CHANNEL_PX + 12 * LANE_PX);
  });

  it('never puts cable 9 on the lane of cable 1, and keeps every lane inside the channel', () => {
    const lanes = 12;
    const xs = Array.from({ length: lanes }, (_, i) => laneX(100, i));
    expect(new Set(xs).size).toBe(lanes);
    expect(xs[8]).not.toBe(xs[0]);
    expect(Math.max(...xs)).toBeLessThan(100 + channelWidth(lanes));
  });
});
