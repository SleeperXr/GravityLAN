import { ref } from 'vue';

/** Whether the app-wide search (Ctrl+K) is open; the sidebar button and the shortcut share it. */
export const commandPaletteOpen = ref(false);

export interface PageCommand {
  kind: 'page';
  id: string;
  to: string;
  label: string;
}

export interface DeviceCommand {
  kind: 'device';
  id: number;
  label: string;
  /** Primary address, shown in mono next to the name */
  ip: string;
  online: boolean;
  /** Everything else that should find the device: host name, MAC, vendor, other addresses */
  extra: string[];
}

export type CommandItem = PageCommand | DeviceCommand;

const MAX_DEVICES = 8;

function words(query: string): string[] {
  return query.toLowerCase().trim().split(/\s+/).filter(Boolean);
}

/** 0 = the name starts with the first word, 1 = the name contains it, 2 = only another field does. */
function rank(label: string, first: string): number {
  const name = label.toLowerCase();
  if (name.startsWith(first)) return 0;
  return name.includes(first) ? 1 : 2;
}

/**
 * The search behind Ctrl+K. Every word must match somewhere (name, address, MAC, host name, vendor).
 * Pages come first, then devices; within each, a name that starts with the query beats one that
 * only contains it, and that beats a match in another field. Without a query: all pages, no devices.
 */
export function searchCommands(query: string, pages: PageCommand[], devices: DeviceCommand[]): CommandItem[] {
  const terms = words(query);
  if (terms.length === 0) return [...pages];

  const matches = (fields: string[]) => {
    const hay = fields.join(' ').toLowerCase();
    return terms.every((term) => hay.includes(term));
  };
  const byRank = <T extends CommandItem>(items: T[]) =>
    items
      .map((item, index) => ({ item, index, rank: rank(item.label, terms[0]) }))
      .sort((a, b) => a.rank - b.rank || a.index - b.index)
      .map(({ item }) => item);

  const foundPages = byRank(pages.filter((p) => matches([p.label])));
  const foundDevices = byRank(devices.filter((d) => matches([d.label, d.ip, ...d.extra]))).slice(0, MAX_DEVICES);
  return [...foundPages, ...foundDevices];
}
