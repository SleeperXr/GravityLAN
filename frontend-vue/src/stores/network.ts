import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { api, createScanSocket } from '@/api/client';
import type { Device, DeviceGroup, Subnet, ScanProgress } from '@/types';

export const useNetworkStore = defineStore('network', () => {
  const devices = ref<Device[]>([]);
  const groups = ref<DeviceGroup[]>([]);
  const subnets = ref<Subnet[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const scanProgress = ref<ScanProgress | null>(null);
  let scanSocket: WebSocket | null = null;

  const onlineDevicesCount = computed(() => devices.value.filter((d) => d.is_online).length);
  const offlineDevicesCount = computed(() => devices.value.filter((d) => !d.is_online).length);
  const activeAgentsCount = computed(() => devices.value.filter((d) => d.has_agent && d.is_online).length);
  const enabledSubnetsCount = computed(() => subnets.value.filter((s) => s.is_enabled).length);
  const isScanning = computed(() => {
    const st = scanProgress.value?.status;
    return st === 'running' || st === 'discovering' || st === 'identifying';
  });

  async function fetchInventory(showLoading = true) {
    if (showLoading) loading.value = true;
    error.value = null;
    try {
      const [devs, grps, subs, scanSt] = await Promise.all([
        api.getDevices(),
        api.getGroups(),
        api.getSubnetsList().catch(() => [] as Subnet[]),
        api.getScanStatus().catch(() => null),
      ]);
      devices.value = devs;
      groups.value = grps;
      subnets.value = subs;
      if (scanSt) scanProgress.value = scanSt;
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load inventory';
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function triggerQuickScan() {
    const enabledCidrs = subnets.value.filter((s) => s.is_enabled).map((s) => s.cidr);
    await api.startDashboardScan({ subnets: enabledCidrs });
    const st = await api.getScanStatus().catch(() => null);
    if (st) scanProgress.value = st;
  }

  function connectScanStream() {
    if (scanSocket && scanSocket.readyState <= WebSocket.OPEN) return;
    scanSocket = createScanSocket((progress) => {
      scanProgress.value = progress;
      if (progress.status === 'completed' || progress.status === 'devices_updated') {
        fetchInventory(false).catch(() => {});
      }
    });
  }

  function disconnectScanStream() {
    if (scanSocket) {
      scanSocket.close();
      scanSocket = null;
    }
  }

  return {
    devices,
    groups,
    subnets,
    loading,
    error,
    scanProgress,
    onlineDevicesCount,
    offlineDevicesCount,
    activeAgentsCount,
    enabledSubnetsCount,
    isScanning,
    fetchInventory,
    triggerQuickScan,
    connectScanStream,
    disconnectScanStream,
  };
});
