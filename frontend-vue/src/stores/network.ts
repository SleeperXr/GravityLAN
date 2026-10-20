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

  // Filters
  const searchQuery = ref('');
  const statusFilter = ref<'all' | 'online' | 'offline'>('all');
  const selectedGroupId = ref<'ALL' | number>('ALL');

  // Counts (both aliases supported)
  const totalCount = computed(() => devices.value.length);
  const onlineCount = computed(() => devices.value.filter((d) => d.is_online).length);
  const offlineCount = computed(() => devices.value.filter((d) => !d.is_online).length);
  const agentCount = computed(() => devices.value.filter((d) => d.has_agent).length);

  const onlineDevicesCount = onlineCount;
  const offlineDevicesCount = offlineCount;
  const activeAgentsCount = computed(() => devices.value.filter((d) => d.has_agent && d.is_online).length);
  const enabledSubnetsCount = computed(() => subnets.value.filter((s) => s.is_enabled).length);

  const isScanning = computed(() => {
    const st = scanProgress.value?.status;
    return Boolean(scanProgress.value?.is_scanning) || st === 'running' || st === 'discovering' || st === 'identifying';
  });

  const filteredDevices = computed(() => {
    const q = searchQuery.value.trim().toLowerCase();
    return devices.value.filter((d) => {
      if (statusFilter.value === 'online' && !d.is_online) return false;
      if (statusFilter.value === 'offline' && d.is_online) return false;
      if (selectedGroupId.value !== 'ALL' && d.group_id !== selectedGroupId.value) return false;
      if (!q) return true;
      const hay = [
        d.name,
        d.hostname,
        d.ip,
        d.mac,
        d.vendor,
        d.os_info,
        d.notes,
        ...(d.services || []).map((s) => `${s.name} ${s.port}`),
        ...(d.interfaces || []).map((i) => `${i.ip} ${i.label || ''}`),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
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

  async function fetchDashboardData() {
    return fetchInventory(false);
  }

  async function updateDevice(id: number, data: Partial<Device>) {
    const updated = await api.updateDevice(id, data);
    const idx = devices.value.findIndex((d) => d.id === id);
    if (idx >= 0) devices.value[idx] = { ...devices.value[idx], ...updated };
    return updated;
  }

  async function deleteDevice(id: number) {
    await api.deleteDevice(id);
    devices.value = devices.value.filter((d) => d.id !== id);
  }

  async function triggerQuickScan() {
    const enabledCidrs = subnets.value.filter((s) => s.is_enabled).map((s) => s.cidr);
    await api.startDashboardScan({ subnets: enabledCidrs });
    const st = await api.getScanStatus().catch(() => null);
    if (st) scanProgress.value = st;
  }

  async function stopScan() {
    await api.stopScan();
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
    searchQuery,
    statusFilter,
    selectedGroupId,
    filteredDevices,
    totalCount,
    onlineCount,
    offlineCount,
    agentCount,
    onlineDevicesCount,
    offlineDevicesCount,
    activeAgentsCount,
    enabledSubnetsCount,
    isScanning,
    fetchInventory,
    fetchDashboardData,
    updateDevice,
    deleteDevice,
    triggerQuickScan,
    stopScan,
    connectScanStream,
    disconnectScanStream,
  };
});
