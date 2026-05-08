/** API client for HomeLan backend. */

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = path;
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `API Error: ${response.status}`);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  // Setup
  getSetupStatus: () => request<{ is_setup_complete: boolean; device_count: number }>('/api/setup/status'),
  completeSetup: (data?: { dns_server?: string }) => 
    request<{ status: string }>('/api/setup/complete', { method: 'POST', body: JSON.stringify(data || {}) }),

  // Scanner
  getSubnets: () => request<import('../types').SubnetInfo[]>('/api/scanner/subnets'),
  startScan: (data: Partial<import('../types').ScanRequest> & { dns_server?: string }) =>
    request<{ status: string }>('/api/scanner/start', { method: 'POST', body: JSON.stringify(data) }),
  startDashboardScan: (data: { subnets: string[] }) => 
    request<{ status: string }>('/api/scanner/start-dashboard', { method: 'POST', body: JSON.stringify(data) }),
  stopScan: () => request<{ status: string }>('/api/scanner/stop', { method: 'POST' }),
  getScanStatus: () => request<import('../types').ScanProgress>('/api/scanner/status'),
  getDiscoveredHosts: () => request<import('../types').Device[]>('/api/scanner/discovered'),
  scanIp: (ip: string) => request<import('../types').Device>(`/api/scanner/scan-ip?ip=${ip}`),
  liveDiscovery: (data: { subnets: string[] }) =>
    request<any[]>(`/api/scanner/live-discovery?subnets=${data.subnets.join(',')}`),
  patchDiscoveredHost: (id: number, data: { custom_name?: string; is_monitored?: boolean }) =>
    request<any>(`/api/scanner/discovered/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  quickSubnetScan: (subnets: string) =>
    request<any>(`/api/scanner/quick-subnet-scan?subnets=${subnets}`, { method: 'POST' }),

  // Devices
  getDevices: () => request<import('../types').Device[]>('/api/devices'),
  getDevice: (id: number) => request<import('../types').Device>(`/api/devices/${id}`),
  addDeviceFromIp: (ip: string) => request<import('../types').Device>(`/api/devices/add-from-ip?ip=${ip}`, { method: 'POST' }),
  updateDevice: (id: number, data: Partial<import('../types').Device>) =>
    request<import('../types').Device>(`/api/devices/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteDevice: (id: number) => request<void>(`/api/devices/${id}`, { method: 'DELETE' }),
  bulkDeleteDevices: (ids: number[]) => request<void>('/api/devices/bulk-delete', { method: 'POST', body: JSON.stringify(ids) }),
  refreshDeviceInfo: (id: number) => request<import('../types').Device>(`/api/devices/${id}/refresh-info`, { method: 'POST' }),
  refreshServices: (id: number) => request<import('../types').Device>(`/api/devices/${id}/refresh-services`, { method: 'POST' }),
  refreshAllDevices: () => request<{status: string, updated_count: number}>('/api/devices/refresh-all', { method: 'POST' }),
  getDeviceHistory: (id: number) => request<import('../types').DeviceHistoryResponse[]>(`/api/devices/${id}/history`),

  // Services
  addService: (deviceId: number, data: any) => request<any>(`/api/devices/${deviceId}/services`, { method: 'POST', body: JSON.stringify(data) }),
  updateService: (serviceId: number, data: any) => request<any>(`/api/services/${serviceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteService: (serviceId: number) => request<void>(`/api/services/${serviceId}`, { method: 'DELETE' }),

  // Groups
  getGroups: () => request<import('../types').DeviceGroup[]>('/api/groups'),
  createGroup: (data: Partial<import('../types').DeviceGroup>) =>
    request<import('../types').DeviceGroup>('/api/groups', { method: 'POST', body: JSON.stringify(data) }),
  updateGroup: (id: number, data: Partial<import('../types').DeviceGroup>) =>
    request<import('../types').DeviceGroup>(`/api/groups/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteGroup: (id: number) => request<void>(`/api/groups/${id}`, { method: 'DELETE' }),
  
  // Settings
  getSettings: () => request<Record<string, string>>('/api/settings'),
  updateSettings: (settings: Record<string, string>) => 
    request<{ status: string }>('/api/settings', { method: 'POST', body: JSON.stringify(settings) }),
  resetDatabase: () => request<{status: string, message: string}>('/api/settings/reset-db', { method: 'POST' }),

  // Agent
  deployAgent: (deviceId: number, data: { ssh_user: string; ssh_password?: string; ssh_key?: string; ssh_port?: number }) =>
    request<{ status: string; message: string; agent_version?: string }>(`/api/agent/deploy/${deviceId}`, { method: 'POST', body: JSON.stringify(data) }),
  uninstallAgent: (deviceId: number, data: { ssh_user: string; ssh_password?: string; ssh_key?: string; ssh_port?: number }) =>
    request<{ status: string; message: string }>(`/api/agent/uninstall/${deviceId}`, { method: 'POST', body: JSON.stringify(data) }),
  getAgentStatus: (deviceId: number) =>
    request<{ device_id: number; is_installed: boolean; is_active: boolean; agent_version?: string; last_seen?: string }>(`/api/agent/status/${deviceId}`),
  getAgentMetrics: (deviceId: number, limit?: number) =>
    request<{ device_id: number; snapshots: any[] }>(`/api/agent/metrics/${deviceId}?limit=${limit || 60}`),
  getAgentConfig: (deviceId: number) =>
    request<{ interval: number; disk_paths: string[]; enable_temp: boolean }>(`/api/agent/config/${deviceId}`),
  updateAgentConfig: (deviceId: number, data: { interval?: number; disk_paths?: string[]; enable_temp?: boolean }) =>
    request<any>(`/api/agent/config/${deviceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
};

/** Create a WebSocket connection for scan progress updates. */
export function createScanSocket(onMessage: (data: import('../types').ScanProgress) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;
  const wsBase = import.meta.env.DEV ? `${protocol}//${host}:8000` : `${protocol}//${window.location.host}`;
  const ws = new WebSocket(`${wsBase}/api/scanner/ws`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch {
      console.warn('Invalid WebSocket message:', event.data);
    }
  };

  ws.onerror = (error) => console.error('WebSocket error:', error);

  return ws;
}

/** Create a WebSocket connection for live agent metrics. */
export function createMetricsSocket(deviceId: number, onMessage: (data: any) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;
  const wsBase = import.meta.env.DEV ? `${protocol}//${host}:8000` : `${protocol}//${window.location.host}`;
  const ws = new WebSocket(`${wsBase}/api/agent/ws/${deviceId}`);

  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      console.warn('Invalid metrics WebSocket message:', event.data);
    }
  };

  ws.onerror = (error) => console.error('Metrics WebSocket error:', error);
  return ws;
}
