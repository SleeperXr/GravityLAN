import { describe, expect, it, vi } from 'vitest';
import type { Device } from '@/types';
import { resolveOrbitSystem, type OrbitLink } from './orbitModel';
import { detectedKind, effectiveKind, matchesSearch, planArrange } from './orbitArrange';

vi.mock('@/lib/networks', () => ({ networkColor: () => 'var(--line-1)' }));

const dev = (id: number, extra: Partial<Device> = {}): Device =>
  ({ id, ip: `10.0.0.${id}`, display_name: `Dev-${id}`, hostname: null, device_type: 'server', device_subtype: '', is_online: true, services: [], parent_id: null, is_wlan: false, is_ap: false, is_host: false, subnet_id: 1, interfaces: [], ...extra }) as Device;
const link = (id: number, source_id: number, target_id: number, extra: Partial<OrbitLink> = {}) => ({ id, source_id, target_id, link_type: '1GbE', ...extra }) as OrbitLink;

// Router 1, a switch 2 on it, an AP 3 on the switch, clients 4–6 hanging on the router (no links)
const devices = [dev(1, { device_type: 'router' }), dev(2, { device_type: 'switch' }), dev(3, { is_ap: true }), dev(4), dev(5, { is_wlan: true }), dev(6)];
const links = [link(1, 1, 2), link(2, 2, 3)];
const bodies = resolveOrbitSystem(devices, links, new Set([1]));

describe('arrange assistant plan', () => {
  it('detects what the map makes of each device', () => {
    expect([1, 2, 3, 4].map((id) => detectedKind(bodies.get(id)!))).toEqual(['star', 'switch', 'ap', 'client']);
    expect(effectiveKind('host', bodies.get(4)!)).toBe('host');
    expect(effectiveKind('auto', bodies.get(4)!)).toBe('client');
  });

  it('turns kinds into roles and hands "auto" back', () => {
    const plan = planArrange(bodies, links, { 6: 'planet' }, { kinds: { 4: 'switch', 5: 'client', 6: 'auto' }, parents: {} });
    expect(plan.roles).toEqual({ 4: 'planet', 5: 'moon' });
    expect(plan.createLinks).toEqual([]);
  });

  it('links clients to the hub they are assigned to, WLAN behind an access point', () => {
    const plan = planArrange(bodies, links, {}, { kinds: {}, parents: { 4: 2, 5: 3, 6: 3 } });
    expect(plan.createLinks).toEqual([
      { source_id: 2, target_id: 4, link_type: '1GbE' },
      { source_id: 3, target_id: 5, link_type: 'WLAN' },
      { source_id: 3, target_id: 6, link_type: 'WLAN' },
    ]);
    expect(plan.removeLinkIds).toEqual([]);
  });

  it('moves a hub to a new uplink, dropping the old one but keeping its own children and backups', () => {
    const more = [...devices, dev(7, { device_type: 'switch' })];
    const wired = [...links, link(3, 1, 7), link(4, 2, 7, { role: 'backup' })];
    const system = resolveOrbitSystem(more, wired, new Set([1]));
    // The AP 3 moves from switch 2 to switch 7
    const plan = planArrange(system, wired, {}, { kinds: {}, parents: { 3: 7 } });
    expect(plan.removeLinkIds).toEqual([2]);
    expect(plan.createLinks).toEqual([{ source_id: 7, target_id: 3, link_type: 'WLAN' }]);

    // Switch 2 moves under switch 7: its link to the router goes, the one to its AP stays; 2–7 is only a backup,
    // so a primary link is made next to it
    const plan2 = planArrange(system, wired, {}, { kinds: {}, parents: { 2: 7 } });
    expect(plan2.removeLinkIds).toEqual([1]);
    expect(plan2.createLinks).toEqual([{ source_id: 7, target_id: 2, link_type: '1GbE' }]);
  });

  it('does not duplicate an existing link and ignores self or unknown parents', () => {
    const plan = planArrange(bodies, links, {}, { kinds: {}, parents: { 2: 1, 4: 4, 5: 99 } });
    expect(plan.createLinks).toEqual([]);
    expect(plan.removeLinkIds).toEqual([]);
  });

  it('searches name, host name and IP', () => {
    expect(matchesSearch(dev(9, { display_name: 'Drucker Büro' }), 'drucker')).toBe(true);
    expect(matchesSearch(dev(9, { hostname: 'nas.lan' }), 'NAS')).toBe(true);
    expect(matchesSearch(dev(9), '10.0.0.9')).toBe(true);
    expect(matchesSearch(dev(9), 'x')).toBe(false);
    expect(matchesSearch(dev(9), '  ')).toBe(true);
  });
});
