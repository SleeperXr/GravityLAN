import { describe, expect, it, vi } from 'vitest';
import type { Device } from '@/types';
import {
  autoOrbitLayout,
  isBackupLink,
  isOnOrbit,
  computeLightBeams,
  computeOrbitRings,
  findDropTargetBody,
  LINK_TYPES,
  linkCount,
  linkTypeOptions,
  moveWithDescendants,
  portLimitReached,
  resolveOrbitSystem,
  roleOf,
  snapToOrbitRing,
  type OrbitLink,
} from './orbitModel';

vi.mock('@/lib/networks', () => ({
  networkColor: (subnetId: number | null | undefined) => `var(--line-${subnetId ?? 1})`,
}));

function makeDevice(overrides: Partial<Device> & { id: number; ip: string }): Device {
  return {
    mac: null,
    hostname: null,
    display_name: `Dev-${overrides.id}`,
    device_type: 'server',
    device_subtype: '',
    group_id: null,
    icon: null,
    sort_order: 0,
    is_pinned: false,
    is_hidden: false,
    x: null,
    y: null,
    w: null,
    h: null,
    notes: null,
    first_seen: '2026-01-01T00:00:00Z',
    last_seen: '2026-01-01T00:00:00Z',
    is_online: true,
    status_changed_at: '2026-01-01T00:00:00Z',
    is_reserved: false,
    virtual_type: null,
    has_agent: false,
    services: [],
    old_ip: null,
    ip_changed_at: null,
    parent_id: null,
    rack_id: null,
    rack_unit: null,
    rack_height: 1,
    topology_x: null,
    topology_y: null,
    is_wlan: false,
    is_ap: false,
    is_host: false,
    subnet_id: 1,
    ...overrides,
  };
}

describe('orbitModel hierarchy and mechanics', () => {
  const devices: Device[] = [
    makeDevice({ id: 1, ip: '192.168.1.1', display_name: 'UniFi Gateway', device_type: 'router' }),
    makeDevice({ id: 2, ip: '192.168.1.2', display_name: 'Core Switch', device_type: 'switch' }),
    makeDevice({ id: 3, ip: '192.168.1.10', display_name: 'Proxmox', is_host: true }),
    makeDevice({ id: 4, ip: '192.168.1.20', display_name: 'AP Obergeschoss', is_ap: true }),
    makeDevice({ id: 5, ip: '192.168.1.11', display_name: 'Docker VM', parent_id: 3, virtual_type: 'vm' }),
    makeDevice({ id: 6, ip: '192.168.1.50', display_name: 'MacBook', is_wlan: true }),
    makeDevice({ id: 7, ip: '192.168.1.60', display_name: 'iPhone', is_wlan: true, is_online: false }),
  ];

  const links: OrbitLink[] = [
    { id: 101, source_id: 1, target_id: 2, link_type: '10GbE' } as OrbitLink,
    { id: 102, source_id: 2, target_id: 3, link_type: '2.5GbE' } as OrbitLink,
    { id: 103, source_id: 2, target_id: 4, link_type: '1GbE' } as OrbitLink,
  ];

  it('assigns star, planets, and moons with solid/dashed/broken orbit styles', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));

    // Gateway is the Star
    expect(bodies.get(1)?.kind).toBe('star');
    expect(bodies.get(1)?.parentId).toBeNull();

    // Core Switch orbits Gateway
    expect(bodies.get(2)?.kind).toBe('planet');
    expect(bodies.get(2)?.parentId).toBe(1);

    // Proxmox & AP orbit Core Switch via BFS over links
    expect(bodies.get(3)?.kind).toBe('planet');
    expect(bodies.get(3)?.parentId).toBe(2);
    expect(bodies.get(4)?.kind).toBe('planet');
    expect(bodies.get(4)?.parentId).toBe(2);

    // Docker VM orbits Proxmox via parent_id
    expect(bodies.get(5)?.kind).toBe('moon');
    expect(bodies.get(5)?.parentId).toBe(3);
    expect(bodies.get(5)?.orbitStyle).toBe('solid');

    // Unlinked WLAN MacBook automatically orbits AP in same subnet on dashed orbit
    expect(bodies.get(6)?.kind).toBe('moon');
    expect(bodies.get(6)?.parentId).toBe(4);
    expect(bodies.get(6)?.orbitStyle).toBe('dashed');

    // Offline iPhone gets broken orbit style
    expect(bodies.get(7)?.parentId).toBe(4);
    expect(bodies.get(7)?.orbitStyle).toBe('broken');
  });

  it('makes small switches and APs dwarf planets and big ones full planets', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));
    expect(roleOf(bodies.get(2)!)).toBe('dwarf'); // switch carrying two planets
    expect(roleOf(bodies.get(4)!)).toBe('dwarf'); // AP with two WLAN moons
    expect(roleOf(bodies.get(3)!)).toBe('planet'); // a host stays a planet
    const many = [...devices, ...[8, 9, 10].map((id) => makeDevice({ id, ip: `192.168.1.${id + 100}` }))];
    const manyLinks = [...links, ...[8, 9, 10].map((id) => ({ id: 200 + id, source_id: 2, target_id: id, link_type: '1GbE' }) as OrbitLink)];
    expect(roleOf(resolveOrbitSystem(many, manyLinks, new Set([1])).get(2)!)).toBe('planet');
  });

  it('follows the roles the user chose', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]), { '2': 'planet', '3': 'dwarf', '6': 'planet' });
    expect(roleOf(bodies.get(2)!)).toBe('planet');
    expect(roleOf(bodies.get(3)!)).toBe('dwarf');
    expect(roleOf(bodies.get(6)!)).toBe('planet');
    // A moon choice cannot hold while others orbit the body: it stays a small hub
    expect(roleOf(resolveOrbitSystem(devices, links, new Set([1]), { '3': 'moon' }).get(3)!)).toBe('dwarf');
    // Choosing a star makes a second system root; the gateway can be demoted
    const swapped = resolveOrbitSystem(devices, links, new Set([1]), { '1': 'planet', '2': 'star' });
    expect(swapped.get(2)?.kind).toBe('star');
    expect(swapped.get(2)?.parentId).toBeNull();
    expect(swapped.get(1)?.kind).toBe('planet');
    expect(swapped.get(1)?.parentId).toBe(2);
  });

  it('colours beams by link type unless the link has its own colour', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));
    const own = [...links.slice(0, 2), { ...links[2], color: '#123456' } as OrbitLink];
    const beams = computeLightBeams(own, bodies, { '10GbE': '#ff0000', '1GbE': '#00ff00' });
    expect(beams.find((b) => b.id === 101)?.color).toBe('#ff0000');
    expect(beams.find((b) => b.id === 102)?.color).toBe('var(--line-1)'); // 2.5GbE has no type colour
    expect(beams.find((b) => b.id === 103)?.color).toBe('#123456');
  });

  it('moves a planet together with all of its moons and sub-moons', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));
    const layout = autoOrbitLayout(devices, links, new Set([1]));

    const swBefore = layout.get(2)!;
    const pveBefore = layout.get(3)!;
    const vmBefore = layout.get(5)!;

    const moved = moveWithDescendants(2, { x: 50, y: -30 }, bodies, layout);

    expect(moved.get(2)).toEqual({ x: swBefore.x + 50, y: swBefore.y - 30 });
    expect(moved.get(3)).toEqual({ x: pveBefore.x + 50, y: pveBefore.y - 30 });
    expect(moved.get(5)).toEqual({ x: vmBefore.x + 50, y: vmBefore.y - 30 });
    // Gateway (Star) did not move
    expect(moved.get(1)).toEqual(layout.get(1));
  });

  it('snaps a dragged moon radius onto a sibling orbit ring within tolerance', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));
    const positions = new Map([
      [4, { x: 0, y: 0 }],
      [6, { x: 100, y: 0 }], // radius 100
      [7, { x: 0, y: 100 }],
    ]);

    // Dragging body 7 to (0, 108) -> distance 108 is within 18px of sibling 6's radius 100
    const snapped = snapToOrbitRing(7, { x: 0, y: 108 }, bodies, positions);
    expect(snapped).toEqual({ x: 0, y: 100 });
  });

  it('detects a drop target planet while preventing dropping onto own descendants', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));
    const positions = new Map([
      [1, { x: 0, y: 0 }],
      [2, { x: 200, y: 0 }],
      [3, { x: 400, y: 0 }],
      [4, { x: 200, y: 200 }],
      [5, { x: 480, y: 0 }],
      [6, { x: 280, y: 200 }],
      [7, { x: 200, y: 280 }],
    ]);

    // Dragging MacBook (6) onto Proxmox (3) at (410, 5) finds Proxmox
    const target = findDropTargetBody(6, { x: 410, y: 5 }, bodies, positions);
    expect(target?.id).toBe(3);

    // Dragging Core Switch (2) onto its own descendant Proxmox (3) is blocked
    const invalidTarget = findDropTargetBody(2, { x: 400, y: 0 }, bodies, positions);
    expect(invalidTarget).toBeNull();
  });

  it('computes light beams and concentric orbit rings', () => {
    const bodies = resolveOrbitSystem(devices, links, new Set([1]));
    const layout = autoOrbitLayout(devices, links, new Set([1]));
    const beams = computeLightBeams(links, bodies);
    const rings = computeOrbitRings(bodies, layout);

    expect(beams).toHaveLength(3);
    expect(beams.every((b) => b.isPrimaryBridge)).toBe(true);
    expect(rings.length).toBeGreaterThan(0);
  });
});

describe('link types and port limits', () => {
  const ends = [
    { source_id: 1, target_id: 2 },
    { source_id: 3, target_id: 1 },
    { source_id: 2, target_id: 3 },
  ];

  it('offers 100 Mb/s and keeps an unknown type of the link selectable', () => {
    expect(LINK_TYPES).toContain('100Mb');
    expect(linkTypeOptions('1GbE')).toEqual([...LINK_TYPES]);
    expect(linkTypeOptions('40GbE')).toEqual([...LINK_TYPES, '40GbE']);
    expect(linkTypeOptions(null)).toEqual([...LINK_TYPES]);
  });

  it('counts the links at either end of a device', () => {
    expect(linkCount(1, ends)).toBe(2);
    expect(linkCount(4, ends)).toBe(0);
  });

  it('reports a full device only when it has a limit', () => {
    expect(portLimitReached({ id: 1, max_ports: 2 }, ends)).toBe(true);
    expect(portLimitReached({ id: 1, max_ports: 3 }, ends)).toBe(false);
    expect(portLimitReached({ id: 1, max_ports: 0 }, ends)).toBe(false);
    expect(portLimitReached({ id: 1, max_ports: null }, ends)).toBe(false);
  });
});

describe('backup links', () => {
  const devices = [
    makeDevice({ id: 1, ip: '10.0.0.1', device_type: 'router' }),
    makeDevice({ id: 2, ip: '10.0.0.2', device_type: 'switch' }),
    makeDevice({ id: 3, ip: '10.0.0.3', device_type: 'switch' }),
    makeDevice({ id: 4, ip: '10.0.0.4', device_type: 'client' }),
  ];
  const primary: OrbitLink[] = [
    { id: 1, source_id: 1, target_id: 2, link_type: 'Fiber' },
    { id: 2, source_id: 2, target_id: 3, link_type: 'Fiber' },
    { id: 3, source_id: 3, target_id: 4, link_type: '1GbE' },
  ] as OrbitLink[];
  // A second path from the router straight to the second switch, as a fallback
  const backup = { id: 9, source_id: 1, target_id: 3, link_type: 'Fiber', role: 'backup' } as OrbitLink;

  it('changes neither hubs, roles nor the automatic layout', () => {
    const before = resolveOrbitSystem(devices, primary, new Set([1]));
    const after = resolveOrbitSystem(devices, [...primary, backup], new Set([1]));
    expect([...after.values()].map((b) => [b.id, b.parentId, b.kind, b.dwarf])).toEqual([...before.values()].map((b) => [b.id, b.parentId, b.kind, b.dwarf]));
    expect(autoOrbitLayout(devices, [...primary, backup], new Set([1]))).toEqual(autoOrbitLayout(devices, primary, new Set([1])));
  });

  it('would re-parent the switch if the same link were primary', () => {
    const asPrimary = resolveOrbitSystem(devices, [...primary, { ...backup, role: 'primary' }], new Set([1]));
    expect(asPrimary.get(3)?.parentId).toBe(1);
  });

  it('is drawn as a backup beam, never as a primary bridge', () => {
    const bodies = resolveOrbitSystem(devices, [...primary, backup], new Set([1]));
    const beam = computeLightBeams([...primary, backup], bodies).find((b) => b.id === 9)!;
    expect(beam.isBackup).toBe(true);
    expect(beam.isPrimaryBridge).toBe(false);
    expect(isBackupLink(backup)).toBe(true);
    expect(isBackupLink(primary[0])).toBe(false);
  });
});

describe('isOnOrbit', () => {
  it('follows the dashboard until the user chooses', () => {
    expect(isOnOrbit({ id: 1, is_hidden: false }, {})).toBe(true);
    expect(isOnOrbit({ id: 2, is_hidden: true }, {})).toBe(false);
  });

  it('lets the user hide a dashboard device or show a hidden one', () => {
    const visibility = { '1': false, '2': true };
    expect(isOnOrbit({ id: 1, is_hidden: false }, visibility)).toBe(false);
    expect(isOnOrbit({ id: 2, is_hidden: true }, visibility)).toBe(true);
  });
});
