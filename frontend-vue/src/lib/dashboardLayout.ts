import type { DeviceGroup } from '@/types';

/** Group id as used in grid class names and the collapsed set; unassigned devices are 'null'. */
export type GroupKey = number | string;

export interface GroupOrderChange {
  groups: DeviceGroup[];
  updates: { id: number; sort_order: number }[];
}

/** Swap a group with its neighbour; null at either end of the list. */
export function swapGroupOrder(groups: DeviceGroup[], group: DeviceGroup, direction: 'up' | 'down'): GroupOrderChange | null {
  const currentIndex = groups.findIndex(g => g.id === group.id);
  if (currentIndex === -1) return null;

  const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
  if (targetIndex < 0 || targetIndex >= groups.length) return null;

  const targetGroup = groups[targetIndex];
  const currentOrder = group.sort_order ?? currentIndex;
  const targetOrder = targetGroup.sort_order ?? targetIndex;

  let newCurrentOrder = targetOrder;
  const newTargetOrder = currentOrder;
  if (newCurrentOrder === newTargetOrder) {
    newCurrentOrder = direction === 'up' ? targetOrder - 1 : targetOrder + 1;
  }

  const next = [...groups];
  next[currentIndex] = { ...group, sort_order: newCurrentOrder };
  next[targetIndex] = { ...targetGroup, sort_order: newTargetOrder };
  next.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
  return {
    groups: next,
    updates: [
      { id: group.id, sort_order: newCurrentOrder },
      { id: targetGroup.id, sort_order: newTargetOrder },
    ],
  };
}
