/**
 * The arrange assistant's plan: what the user said each device is, which hub it hangs on and which devices hang on
 * a hub, turned into orbit roles and topology links. The assistant applies the plan and then lays the map out.
 */
import type { Device } from '@/types';
import { isBackupLink, isNetworkGear, type OrbitBody, type OrbitLink, type OrbitRole, type OrbitRoles } from './orbitModel';

/** What the user picks per device; "auto" leaves the decision to the map. */
export type ArrangeKind = 'auto' | 'star' | 'switch' | 'ap' | 'host' | 'client';
export const ARRANGE_KINDS: ArrangeKind[] = ['auto', 'star', 'switch', 'ap', 'host', 'client'];

const ROLE_OF: Record<ArrangeKind, OrbitRole | null> = {
  auto: null,
  star: 'star',
  switch: 'planet',
  ap: 'planet',
  host: 'planet',
  client: 'moon',
};

/** What the map currently makes of a device, in the assistant's words. */
export function detectedKind(body: OrbitBody): Exclude<ArrangeKind, 'auto'> {
  if (body.kind === 'star') return 'star';
  if (body.kind === 'moon') return 'client';
  const d = body.device;
  if (d.is_ap || (d.device_type || '').toLowerCase() === 'ap') return 'ap';
  if (d.is_host) return 'host';
  return isNetworkGear(d) ? 'switch' : 'host';
}

/** The kind that counts for a device: the user's pick, else what the map detected. */
export const effectiveKind = (choice: ArrangeKind | undefined, body: OrbitBody) =>
  !choice || choice === 'auto' ? detectedKind(body) : choice;

export const isHubKind = (kind: ArrangeKind) => kind === 'switch' || kind === 'ap' || kind === 'host';

export interface ArrangeChoices {
  /** Device id -> what it is */
  kinds: Record<number, ArrangeKind>;
  /** Device id -> the device it hangs on (uplink of a hub, or the hub a client is assigned to) */
  parents: Record<number, number>;
}

export interface ArrangePlan {
  roles: OrbitRoles;
  removeLinkIds: number[];
  createLinks: { source_id: number; target_id: number; link_type: string }[];
}

/**
 * Roles and link changes for the user's choices. A device with a new parent loses its primary links to the other
 * stars and hubs it hung on (links to its own children and backup links stay) and gets one link to the new parent,
 * unless that link exists already. WLAN when an access point or a WLAN client is involved, else 1GbE.
 */
export function planArrange(
  bodies: Map<number, OrbitBody>,
  links: OrbitLink[],
  current: OrbitRoles,
  choices: ArrangeChoices,
): ArrangePlan {
  const roles: OrbitRoles = { ...current };
  for (const [id, kind] of Object.entries(choices.kinds)) {
    const role = ROLE_OF[kind];
    if (role) roles[id] = role;
    else delete roles[id];
  }

  const kindOf = (id: number) => {
    const body = bodies.get(id);
    return body ? effectiveKind(choices.kinds[id], body) : 'client';
  };
  const isHub = (id: number) => kindOf(id) === 'star' || isHubKind(kindOf(id));
  const parentOf = (id: number) => choices.parents[id] ?? bodies.get(id)?.parentId ?? null;

  const removeLinkIds = new Set<number>();
  const createLinks: ArrangePlan['createLinks'] = [];
  for (const [key, parentId] of Object.entries(choices.parents)) {
    const id = Number(key);
    if (!bodies.has(id) || !bodies.has(parentId) || id === parentId) continue;
    for (const l of links) {
      if (isBackupLink(l) || (l.source_id !== id && l.target_id !== id)) continue;
      const other = l.source_id === id ? l.target_id : l.source_id;
      // A link to a hub that hangs on this device is one of its children: it stays
      if (other !== parentId && isHub(other) && parentOf(other) !== id) removeLinkIds.add(l.id);
    }
    const exists = links.some(
      (l) => !isBackupLink(l) && ((l.source_id === parentId && l.target_id === id) || (l.source_id === id && l.target_id === parentId)),
    );
    if (!exists) {
      const wireless = kindOf(parentId) === 'ap' || kindOf(id) === 'ap' || Boolean(bodies.get(id)!.device.is_wlan);
      createLinks.push({ source_id: parentId, target_id: id, link_type: wireless ? 'WLAN' : '1GbE' });
    }
  }
  return { roles, removeLinkIds: [...removeLinkIds], createLinks };
}

/** Devices matching a search over name, host name and IP (empty search: all). */
export function matchesSearch(device: Device, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [device.display_name, device.hostname, device.ip].some((v) => (v || '').toLowerCase().includes(q));
}
