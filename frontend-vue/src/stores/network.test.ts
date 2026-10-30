import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import type { Device, ScanProgress } from '@/types';

const api = vi.hoisted(() => ({
  getDevices: vi.fn(),
  getGroups: vi.fn(),
  getSubnetsList: vi.fn(),
  getScanStatus: vi.fn(),
  stopScan: vi.fn(),
}));
const socket = vi.hoisted(() => ({ onProgress: null as ((p: ScanProgress) => void) | null }));

vi.mock('@/api/client', () => ({
  api,
  createScanSocket: vi.fn((cb: (p: ScanProgress) => void) => {
    socket.onProgress = cb;
    return { readyState: 1, close: vi.fn() };
  }),
}));

import { useNetworkStore } from './network';

const device = (id: number, extra: Partial<Device> = {}) =>
  ({ id, ip: `10.0.0.${id}`, is_online: true, has_agent: false, ...extra }) as Device;

const progress = (status: string): ScanProgress =>
  ({ status, current_subnet: '10.0.0.0/24', hosts_scanned: 0, hosts_total: 0, devices_found: 0, message: '', timestamp: '' }) as ScanProgress;

describe('network store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    api.getDevices.mockResolvedValue([device(1), device(2, { is_online: false, has_agent: true })]);
    api.getGroups.mockResolvedValue([
      { id: 2, name: 'B', sort_order: 2 },
      { id: 1, name: 'A', sort_order: 1 },
    ]);
    api.getSubnetsList.mockResolvedValue([{ cidr: '10.0.0.0/24' }]);
    api.getScanStatus.mockResolvedValue(progress('idle'));
    api.stopScan.mockResolvedValue(undefined);
  });

  it('loads the inventory and derives the counts', async () => {
    const store = useNetworkStore();
    await store.loadData();

    expect(store.loaded).toBe(true);
    expect(store.isLoading).toBe(false);
    expect(store.error).toBeNull();
    expect(store.lastUpdated).toBeInstanceOf(Date);
    expect([store.totalCount, store.onlineCount, store.offlineCount, store.agentCount]).toEqual([2, 1, 1, 1]);
    expect(store.sortedGroups.map((g) => g.name)).toEqual(['A', 'B']);
  });

  it('keeps dashboard-hidden devices apart, for the orbit map only', async () => {
    api.getDevices.mockResolvedValue([device(1), device(2, { is_hidden: true })]);
    const store = useNetworkStore();
    await store.loadData();

    expect(api.getDevices).toHaveBeenCalledWith(true);
    expect(store.devices.map((d) => d.id)).toEqual([1]);
    expect(store.hiddenDevices.map((d) => d.id)).toEqual([2]);
    expect(store.totalCount).toBe(1);

    // Showing it on the dashboard again moves it over
    store.patchDevice(2, { is_hidden: false });
    expect(store.devices.map((d) => d.id)).toEqual([1, 2]);
    expect(store.hiddenDevices).toEqual([]);
  });

  it('shares one request between overlapping loads', async () => {
    const store = useNetworkStore();
    await Promise.all([store.loadData(), store.loadData(true)]);

    expect(api.getDevices).toHaveBeenCalledTimes(1);
  });

  it('keeps the old subnets when only the subnet list fails', async () => {
    const store = useNetworkStore();
    await store.loadData();
    api.getSubnetsList.mockRejectedValueOnce(new Error('offline'));
    await store.loadData(true);

    expect(store.subnets).toEqual([{ cidr: '10.0.0.0/24' }]);
    expect(store.error).toBeNull();
  });

  it('keeps the last inventory and reports the error when devices fail', async () => {
    const store = useNetworkStore();
    await store.loadData();
    api.getDevices.mockRejectedValueOnce(new Error('boom'));
    await store.loadData(true);

    expect(store.error).toBe('boom');
    expect(store.totalCount).toBe(2);
    expect(store.isLoading).toBe(false);
  });

  it('patches one device in place', async () => {
    const store = useNetworkStore();
    await store.loadData();
    store.patchDevice(2, { is_online: true });

    expect(store.onlineCount).toBe(2);
  });

  it('treats every in-progress status as scanning', () => {
    const store = useNetworkStore();
    store.markScanStarted('10.0.0.0/24');
    expect(store.isScanning).toBe(true);

    store.scanProgress = progress('devices_updated');
    expect(store.isScanning).toBe(true);

    store.scanProgress = progress('completed');
    expect(store.isScanning).toBe(false);
  });

  it('reloads the inventory when the scan stream reports new devices', async () => {
    const store = useNetworkStore();
    store.connectScanStream();
    store.connectScanStream();
    socket.onProgress?.(progress('discovering'));
    expect(api.getDevices).not.toHaveBeenCalled();

    socket.onProgress?.(progress('completed'));
    await vi.waitFor(() => expect(api.getDevices).toHaveBeenCalledTimes(1));
    expect(store.scanProgress?.status).toBe('completed');
  });

  it('stopScan refreshes the status even when the stop request fails', async () => {
    const store = useNetworkStore();
    api.stopScan.mockRejectedValueOnce(new Error('nope'));
    api.getScanStatus.mockResolvedValueOnce(progress('cancelled'));
    await store.stopScan();

    expect(store.scanProgress?.status).toBe('cancelled');
  });
});
