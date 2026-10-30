/** First-run wizard logic, ported from the React UI (Setup/SetupWizard.tsx, Setup/setupHooks.ts). */
import type { ScanProgress, SubnetInfo } from '@/types';
import { canonicalCidr } from '@/lib/subnetModel';

export const STEP_KEYS = ['step_welcome', 'step_networks', 'step_scan', 'step_security'] as const;
export const NETWORKS_STEP = 1;
export const SCAN_STEP = 2;
export const SECURITY_STEP = 3;

export type StepState = 'skipped' | 'done' | 'current' | 'todo';

/** `skipped`: a passed step that did not complete (scan skipped or failed), shown without a check. */
export function stepState(index: number, current: number, skipped?: number): StepState {
  if (index === skipped && index < current) return 'skipped';
  if (index < current) return 'done';
  return index === current ? 'current' : 'todo';
}

export const SCAN_FINISHED: ScanProgress['status'][] = ['completed', 'failed', 'cancelled'];

/**
 * A network the container has no interface in (e.g. an IoT VLAN behind the router), added to the
 * list and selected; null when the input is no IPv4 subnet of at most /16.
 */
export function addCustomNetwork(subnets: SubnetInfo[], selected: string[], input: string): { subnets: SubnetInfo[]; selected: string[] } | null {
  const subnet = canonicalCidr(input, 16);
  if (!subnet) return null;
  return {
    subnets: subnets.some((s) => s.subnet === subnet) ? subnets : [...subnets, { interface_name: '', ip_address: '', subnet, netmask: '', is_up: true }],
    selected: selected.includes(subnet) ? selected : [...selected, subnet],
  };
}

export function scanPercent(progress: ScanProgress | null): number | null {
  const total = progress?.hosts_total ?? 0;
  return total > 0 ? Math.min(100, Math.round(((progress?.hosts_scanned ?? 0) / total) * 100)) : null;
}
