import { describe, expect, it, vi } from 'vitest';
import type { Device } from '@/types';
import { resolveOrbitSystem, type OrbitLink } from './orbitModel';
import { BODY_RADIUS, beamPath, labelSize, layoutOrbit, orbitCenterId, placeLabels } from './orbitLayout';

vi.mock('@/lib/networks', () => ({
  networkColor: (subnetId: number | null | undefined) => `var(--line-${subnetId ?? 1})`,
}));

const dev = (id: number, extra: Partial<Device> = {}): Device =>
  ({ id, ip: `192.168.1.${id}`, display_name: `Dev-${id}`, hostname: null, device_type: 'server', device_subtype: '', is_online: true, services: [], parent_id: null, is_wlan: false, is_ap: false, is_host: false, subnet_id: 1, interfaces: [], ...extra }) as Device;
const link = (id: number, source_id: number, target_id: number, link_type = '1GbE') => ({ id, source_id, target_id, link_type }) as OrbitLink;

// A typical home lab: router -> one core switch -> everything else
const devices = [
  dev(1, { device_type: 'router' }),
  dev(2, { device_type: 'switch' }),
  dev(3, { is_host: true }),
  dev(4, { is_host: true }),
  dev(5, { is_ap: true }),
  dev(6, { is_ap: true }),
  dev(7),
  dev(8),
  dev(10, { parent_id: 3, virtual_type: 'vm' }),
  dev(11, { parent_id: 3, virtual_type: 'vm' }),
  dev(12, { parent_id: 4, virtual_type: 'docker' }),
  dev(20, { is_wlan: true }),
  dev(21, { is_wlan: true, is_online: false }),
];
const links = [link(1, 1, 2, '10GbE'), link(2, 2, 3), link(3, 2, 4), link(4, 2, 5), link(5, 2, 6), link(6, 2, 7), link(7, 2, 8)];
const bodies = resolveOrbitSystem(devices, links, new Set([1]));
const pos = layoutOrbit(bodies);
const angle = (id: number) => Math.atan2(pos.get(id)!.y, pos.get(id)!.x);

describe('orbit layout', () => {
  it('puts the router at the centre, even when only a core switch hangs off it', () => {
    expect(pos.get(1)).toEqual({ x: 0, y: 0 });
    // The hosts and APs behind the switch spread around the router, not into one corner
    const quadrants = new Set([3, 4, 5, 6].map((id) => `${Math.sign(pos.get(id)!.x)}/${Math.sign(pos.get(id)!.y)}`));
    expect(quadrants.size).toBe(4);
  });

  it('puts planets of one tier on one ring around the star, outside the tier before', () => {
    const r = (id: number) => Math.round(Math.hypot(pos.get(id)!.x, pos.get(id)!.y));
    expect(new Set([3, 4, 5, 6].map(r)).size).toBe(1);
    expect(r(3)).toBeGreaterThan(r(2));
  });

  it('keeps every pair of bodies apart', () => {
    const ids = [...pos.keys()];
    for (let i = 0; i < ids.length; i++)
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos.get(ids[i])!;
        const b = pos.get(ids[j])!;
        expect(Math.hypot(a.x - b.x, a.y - b.y), `${ids[i]}–${ids[j]}`).toBeGreaterThan(60);
      }
  });

  it('fans moons around their planet away from the star', () => {
    // VMs of host 3 sit further out than the host itself
    const host = Math.hypot(pos.get(3)!.x, pos.get(3)!.y);
    for (const vm of [10, 11]) expect(Math.hypot(pos.get(vm)!.x, pos.get(vm)!.y)).toBeGreaterThan(host - 1);
    expect(Math.abs(angle(10) - angle(3))).toBeLessThan(0.6);
  });

  it('orbits moons around their parent and planets around their star', () => {
    expect(orbitCenterId(bodies.get(10)!, bodies)).toBe(3);
    expect(orbitCenterId(bodies.get(3)!, bodies)).toBe(1);
    expect(orbitCenterId(bodies.get(1)!, bodies)).toBeNull();
  });

  it('lays out two routers as two systems side by side', () => {
    const two = layoutOrbit(resolveOrbitSystem([dev(1, { device_type: 'router' }), dev(2, { device_type: 'router' }), dev(3, { subnet_id: 1 })], [], new Set([1, 2])));
    expect(two.get(1)!.y).toBe(two.get(2)!.y);
    expect(two.get(2)!.x - two.get(1)!.x).toBeGreaterThan(200);
  });
});

describe('orbit labels', () => {
  it('moves a label off a neighbour sitting right below', () => {
    const size = labelSize('Home Assistant', '192.168.1.21', false);
    const placed = placeLabels([
      { id: 1, pos: { x: 0, y: 0 }, radius: BODY_RADIUS.moon, size, rank: 2 },
      { id: 2, pos: { x: 0, y: 40 }, radius: BODY_RADIUS.moon, size, rank: 2 },
    ]);
    expect(placed.get(1)!.side).not.toBe('below');
  });

  it('keeps the label below when there is room', () => {
    const placed = placeLabels([{ id: 1, pos: { x: 0, y: 0 }, radius: 16, size: labelSize('Proxmox', '10.0.0.1', false), rank: 1 }]);
    expect(placed.get(1)).toMatchObject({ side: 'below', anchor: 'middle' });
  });
});

describe('orbit beams', () => {
  it('bends beams between bodies on opposite sides along the orbit instead of across the star', () => {
    const { d, mid } = beamPath({ x: 0, y: -300 }, { x: 0, y: 300 }, { x: 0, y: 0 });
    expect(d).toContain('Q');
    expect(Math.hypot(mid.x, mid.y)).toBeGreaterThan(250);
  });

  it('keeps short beams and beams to the star straight', () => {
    expect(beamPath({ x: 0, y: -300 }, { x: 20, y: -320 }, { x: 0, y: 0 }).d).not.toContain('Q');
    expect(beamPath({ x: 0, y: 0 }, { x: 0, y: -300 }, { x: 0, y: 0 }).d).not.toContain('Q');
  });
});
