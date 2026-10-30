import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api, createScanSocket } from '@/api/client';
import type { Device, DeviceGroup, ScanProgress, Subnet } from '@/types';

/** Scan states that mean the scan is still going (the backend sends 'devices_updated' mid-scan). */
export const SCAN_ACTIVE: ScanProgress['status'][] = ['running', 'discovering', 'identifying', 'devices_updated'];

/** Inventory shared by the dashboard, the sidebar counts and the editors. */
export const useNetworkStore = defineStore('network', () => {
  const devices = ref<Device[]>([]);
  /** Devices hidden from the dashboard; only the orbit map may show them (`ui.orbit_visibility`) */
  const hiddenDevices = ref<Device[]>([]);
  const groups = ref<DeviceGroup[]>([]);
  const subnets = ref<Subnet[]>([]);
  const isLoading = ref(true);
  const loaded = ref(false);
  const error = ref<string | null>(null);
  /** When the inventory last loaded successfully, for the overview's freshness note */
  const lastUpdated = ref<Date | null>(null);
  const scanProgress = ref<ScanProgress | null>(null);
  let scanSocket: WebSocket | null = null;
  let inflight: Promise<void> | null = null;

  const totalCount = computed(() => devices.value.length);
  const onlineCount = computed(() => devices.value.filter((d) => d.is_online).length);
  const offlineCount = computed(() => totalCount.value - onlineCount.value);
  const agentCount = computed(() => devices.value.filter((d) => d.has_agent).length);
  const isScanning = computed(() => !!scanProgress.value && SCAN_ACTIVE.includes(scanProgress.value.status));
  const sortedGroups = computed(() => [...groups.value].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)));

  /** Devices, groups and subnets. `silent` keeps the current view while reloading. */
  function loadData(silent = false): Promise<void> {
    if (inflight) return inflight;
    if (!silent && !loaded.value) isLoading.value = true;
    inflight = (async () => {
      try {
        const [devs, grps, subs] = await Promise.all([
          api.getDevices(true),
          api.getGroups(),
          api.getSubnetsList().catch(() => subnets.value),
        ]);
        devices.value = devs.filter((d) => !d.is_hidden);
        hiddenDevices.value = devs.filter((d) => d.is_hidden);
        groups.value = grps;
        subnets.value = subs;
        loaded.value = true;
        lastUpdated.value = new Date();
        error.value = null;
      } catch (err) {
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        isLoading.value = false;
        inflight = null;
      }
    })();
    return inflight;
  }

  /** First load after sign-in, plus the current scan state. */
  async function fetchInventory(showLoading = true) {
    await loadData(!showLoading);
    api.getScanStatus().then((st) => (scanProgress.value = st)).catch(() => {});
  }

  function patchDevice(id: number, data: Partial<Device>) {
    const all = [...devices.value, ...hiddenDevices.value].map((d) => (d.id === id ? { ...d, ...data } : d));
    devices.value = all.filter((d) => !d.is_hidden);
    hiddenDevices.value = all.filter((d) => d.is_hidden);
  }

  function markScanStarted(subnet: string) {
    scanProgress.value = {
      status: 'running',
      current_subnet: subnet,
      hosts_scanned: 0,
      hosts_total: 0,
      devices_found: 0,
      message: '',
      timestamp: new Date().toISOString(),
    };
  }

  async function stopScan() {
    await api.stopScan().catch(() => {});
    scanProgress.value = await api.getScanStatus().catch(() => scanProgress.value);
  }

  function connectScanStream() {
    if (scanSocket && scanSocket.readyState <= WebSocket.OPEN) return;
    scanSocket = createScanSocket((progress) => {
      scanProgress.value = progress;
      const status = String(progress.status).toLowerCase();
      if (status === 'completed' || status === 'devices_updated') void loadData(true);
    });
  }

  function disconnectScanStream() {
    scanSocket?.close();
    scanSocket = null;
  }

  return {
    devices,
    hiddenDevices,
    groups,
    sortedGroups,
    subnets,
    isLoading,
    loaded,
    lastUpdated,
    error,
    scanProgress,
    totalCount,
    onlineCount,
    offlineCount,
    agentCount,
    isScanning,
    loadData,
    fetchInventory,
    patchDevice,
    markScanStarted,
    stopScan,
    connectScanStream,
    disconnectScanStream,
  };
});
