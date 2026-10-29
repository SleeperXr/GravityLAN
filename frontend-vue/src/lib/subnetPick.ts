import type { Device, DiscoveredHost, Subnet } from '@/types';

/** The /24 prefix ("192.168.1") of a CIDR or address, or null when it has none. */
function prefixOfAddress(value: string | null | undefined): string | null {
  return value?.match(/^(\d+\.\d+\.\d+)\./)?.[1] ?? null;
}

/**
 * The /24 the IP planner opens on when the user has not picked one: the subnet with the most
 * addresses in use (devices, their interfaces, discovered hosts), so it does not start on an empty
 * guest network. Ties keep the subnet order; with no subnets, the /24 of the first device.
 */
export function busiestPrefix(subnets: Pick<Subnet, 'cidr'>[], devices: Pick<Device, 'ip' | 'interfaces'>[], discovered: Pick<DiscoveredHost, 'ip'>[]): string {
  const used = new Map<string, Set<string>>();
  const note = (raw: string | null | undefined) => {
    const ip = raw?.trim();
    const prefix = prefixOfAddress(ip);
    if (!prefix || !ip) return;
    used.set(prefix, (used.get(prefix) ?? new Set()).add(ip));
  };
  for (const device of devices) {
    note(device.ip);
    device.interfaces?.forEach((i) => note(i.ip));
  }
  discovered.forEach((host) => note(host.ip));

  let best = '';
  let bestCount = -1;
  for (const subnet of subnets) {
    const prefix = prefixOfAddress(subnet.cidr) ?? '';
    const count = used.get(prefix)?.size ?? 0;
    if (prefix && count > bestCount) {
      best = prefix;
      bestCount = count;
    }
  }
  return best || prefixOfAddress(devices[0]?.ip) || '';
}
