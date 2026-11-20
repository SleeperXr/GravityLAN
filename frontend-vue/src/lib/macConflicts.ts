import type { MacChangeRequest, MacConflictDevice, MacConflictGroup } from '@/types';
import { t } from '@/i18n';

export interface DeviceMacConflict {
  group: MacConflictGroup;
  device: MacConflictDevice;
}

/** Stable identifier for one (documented, observed) MAC conflict group. */
export function macConflictGroupKey(group: MacConflictGroup): string {
  return `${group.documented_mac ?? 'none'}->${group.observed_mac}`;
}

/** True when more than one device shares the old MAC and saw the same new MAC (e.g. ipvlan host). */
export function hasSharedDevices(group: MacConflictGroup): boolean {
  return group.devices.length > 1;
}

/** Open conflicts that include the given device, preserving server order. */
export function conflictsForDevice(groups: MacConflictGroup[], deviceId: number): DeviceMacConflict[] {
  const result: DeviceMacConflict[] = [];
  for (const group of groups) {
    const device = group.devices.find((entry) => entry.id === deviceId);
    if (device) result.push({ group, device });
  }
  return result;
}

/** Distinct observation sources in a conflict group, preserving first-seen order. */
export function groupSources(group: MacConflictGroup): string[] {
  const seen = new Set<string>();
  const sources: string[] = [];
  for (const entry of group.devices) {
    if (!seen.has(entry.source)) {
      seen.add(entry.source);
      sources.push(entry.source);
    }
  }
  return sources;
}

/** Build the payload for PUT /api/devices/{id}/mac; apply_to_shared is only ever true for multi-device groups. */
export function buildAdoptPayload(group: MacConflictGroup, applyToShared: boolean): MacChangeRequest {
  return {
    mac: group.observed_mac,
    apply_to_shared: hasSharedDevices(group) && applyToShared,
  };
}

/** Localised label for a conflict observation source; unknown sources stay as sent. */
export function sourceLabel(source: string): string {
  const key = `gv.mac_conflicts.source_${source.toLowerCase()}`;
  const label = t(key);
  return label === key ? source : label;
}
