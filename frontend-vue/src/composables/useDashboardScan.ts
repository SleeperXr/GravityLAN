import { onBeforeUnmount, ref } from 'vue';
import { api } from '@/api/client';
import { SCAN_ACTIVE, useNetworkStore } from '@/stores/network';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/** A subnet the dashboard scan can target, with a line saying what it is. */
export interface ScanTarget {
  subnet: string;
  label: string;
}

/** The enabled scan subnets of the network overview; only without any, the container's own interfaces. */
export async function loadScanTargets(): Promise<ScanTarget[]> {
  let configured: { cidr: string; name: string }[] = [];
  try {
    const list = await api.getSubnetsList();
    configured = Array.isArray(list) ? list.filter((s) => s.is_enabled !== false) : [];
  } catch {
    // fall back to the local interfaces
  }
  if (configured.length > 0) return configured.map((s) => ({ subnet: s.cidr, label: s.name }));
  return (await api.getSubnets()).map((s) => ({ subnet: s.subnet, label: `Interface: ${s.interface_name} (${s.ip_address})` }));
}

/** Subnet picker and dashboard scan, with progress polling every 5 s (as in the React UI). */
export function useDashboardScan() {
  const store = useNetworkStore();
  const { showToast } = useToast();
  const dialogOpen = ref(false);
  const targets = ref<ScanTarget[]>([]);
  const starting = ref(false);
  let timer: number | undefined;

  function stopPolling() {
    if (timer) window.clearInterval(timer);
    timer = undefined;
  }

  function poll() {
    stopPolling();
    timer = window.setInterval(async () => {
      try {
        const progress = await api.getScanStatus();
        store.scanProgress = progress;
        if (SCAN_ACTIVE.includes(progress.status)) return;
        stopPolling();
        await store.loadData(true);
        if (progress.status === 'failed') {
          showToast('error', t('notifications.scan_failed'), progress.message || t('notifications.scan_failed_text'));
        } else {
          showToast('success', t('notifications.scan_completed'), t('setup.devices_found', { count: progress.devices_found ?? 0 }));
        }
      } catch {
        // keep polling; the next tick may succeed
      }
    }, 5000);
  }

  async function openDialog() {
    try {
      const list = await loadScanTargets();
      if (list.length === 0) {
        showToast('error', t('notifications.scan_failed'), t('gv.scan.no_targets'));
        return;
      }
      targets.value = list;
      dialogOpen.value = true;
    } catch (err) {
      showToast('error', t('notifications.scan_failed'), err instanceof Error ? err.message : String(err));
    }
  }

  /** `subnet` null scans every target in the list. */
  async function startScan(subnet: string | null) {
    starting.value = true;
    try {
      const subnets = subnet ? [subnet] : targets.value.map((s) => s.subnet);
      const res = await api.startDashboardScan({ subnets });
      if (res.status !== 'ok') {
        showToast('error', t('notifications.scan_failed'), (res as { message?: string }).message ?? '');
        return;
      }
      dialogOpen.value = false;
      store.markScanStarted(subnets.join(', '));
      showToast('info', t('common.scan_started'), subnets.join(', '));
      poll();
    } catch (err) {
      showToast('error', t('notifications.scan_failed'), err instanceof Error ? err.message : String(err));
    } finally {
      starting.value = false;
    }
  }

  onBeforeUnmount(stopPolling);

  return { dialogOpen, targets, starting, openDialog, startScan };
}
