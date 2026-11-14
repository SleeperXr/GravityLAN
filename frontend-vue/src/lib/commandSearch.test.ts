import { describe, expect, it } from 'vitest';
import { searchCommands, type DeviceCommand, type PageCommand } from './commandSearch';

const page = (id: string, label: string): PageCommand => ({ kind: 'page', id, to: `/${id}`, label });
const device = (id: number, label: string, ip: string, extra: string[] = []): DeviceCommand => ({ kind: 'device', id, label, ip, online: true, extra });

const pages = [page('dashboard', 'Übersicht'), page('health', 'Health-Radar'), page('agents', 'Agents')];
const devices = [
  device(1, 'Synology NAS', '192.168.100.12', ['nas.lan', 'aa:bb:cc:dd:ee:01', 'Synology']),
  device(2, 'Proxmox', '192.168.100.10', ['pve.lan']),
  device(3, 'Home Assistant', '192.168.100.40', ['ha.lan']),
  device(4, 'Assist Box', '192.168.100.41'),
];

const ids = (items: ReturnType<typeof searchCommands>) => items.map((i) => `${i.kind}:${i.id}`);

describe('searchCommands', () => {
  it('lists every page and no device without a query', () => {
    expect(ids(searchCommands('  ', pages, devices))).toEqual(['page:dashboard', 'page:health', 'page:agents']);
  });

  it('finds devices by address, MAC and host name, not only by name', () => {
    expect(ids(searchCommands('100.10', pages, devices))).toEqual(['device:2']);
    expect(ids(searchCommands('AA:BB', pages, devices))).toEqual(['device:1']);
    expect(ids(searchCommands('pve', pages, devices))).toEqual(['device:2']);
  });

  it('needs every word to match', () => {
    expect(ids(searchCommands('synology 100.12', pages, devices))).toEqual(['device:1']);
    expect(ids(searchCommands('synology 100.10', pages, devices))).toEqual([]);
  });

  it('puts pages first and a name that starts with the query before one that only contains it', () => {
    expect(ids(searchCommands('assist', pages, devices))).toEqual(['device:4', 'device:3']);
    expect(ids(searchCommands('a', pages, devices)).slice(0, 1)).toEqual(['page:agents']);
  });

  it('shows at most eight devices', () => {
    const many = Array.from({ length: 12 }, (_, i) => device(i + 10, `Host ${i}`, `10.0.0.${i}`));
    expect(searchCommands('host', [], many)).toHaveLength(8);
  });
});
