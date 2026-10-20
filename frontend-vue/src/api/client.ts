/** API client for GravityUI (Vue 3) sharing the FastAPI backend session cookie. */
import type {
  AgentSnapshot,
  AgentSummary,
  ApiTokenCreated,
  ApiTokenResponse,
  Device,
  DeviceGroup,
  DeviceHealthDetailResponse,
  DeviceHistoryResponse,
  DeviceInterface,
  DiscoveredHost,
  GatewayEntry,
  GlobalMetricPoint,
  HealthOverviewResponse,
  MergeSuggestion,
  Rack,
  ScanProgress,
  ScanRequest,
  Service,
  Subnet,
  SubnetInfo,
  TopologyLink,
} from '@/types';

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let token = localStorage.getItem('gravitylan_token');
  if (token === 'undefined') token = null;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options?.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(path, {
    credentials: 'include',
    headers,
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const err = new Error(formatErrorDetail(error.detail) || `API Error: ${response.status}`) as Error & { status?: number };
    err.status = response.status;
    throw err;
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

function formatErrorDetail(detail: unknown): string {
  if (Array.isArray(detail)) return detail.map((item) => item?.msg ?? String(item)).join('; ');
  return typeof detail === 'string' ? detail : '';
}

export const api = {
  getSetupStatus: () => request<{ is_setup_complete: boolean; device_count: number; version?: string }>('/api/setup/status'),
  checkAuth: () => request<{ status: string }>('/api/auth/check', { method: 'POST' }),
  login: (password: string) =>
    request<{ status: string; token?: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }).then((res) => {
      if (res.token) {
        localStorage.setItem('gravitylan_token', res.token);
      } else {
        localStorage.removeItem('gravitylan_token');
      }
      return res;
    }),
  logout: () =>
    request<{ status: string }>('/api/auth/logout', { method: 'POST' }).then(() => {
      localStorage.removeItem('gravitylan_token');
    }),

  // Devices
  getDevices: () => request<Device[]>('/api/devices'),
  getDevice: (id: number) => request<Device>(`/api/devices/${id}`),
  addDeviceFromIp: (ip: string) => request<Device>(`/api/devices/add-from-ip?ip=${encodeURIComponent(ip)}`, { method: 'POST' }),
  updateDevice: (id: number, data: Partial<Device>) =>
    request<Device>(`/api/devices/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteDevice: (id: number) => request<void>(`/api/devices/${id}`, { method: 'DELETE' }),
  bulkDeleteDevices: (ids: number[]) =>
    request<void>('/api/devices/bulk-delete', { method: 'POST', body: JSON.stringify(ids) }),
  refreshDeviceInfo: (id: number) => request<Device>(`/api/devices/${id}/refresh-info`, { method: 'POST' }),
  refreshServices: (id: number) => request<Device>(`/api/devices/${id}/refresh-services`, { method: 'POST' }),
  refreshAllDevices: () => request<{ status: string; updated_count: number }>('/api/devices/refresh-all', { method: 'POST' }),
  getDeviceHistory: (id: number) => request<DeviceHistoryResponse[]>(`/api/devices/${id}/history`),

  // Interfaces & Gateways
  getDeviceInterfaces: (deviceId: number) => request<DeviceInterface[]>(`/api/devices/${deviceId}/interfaces`),
  addDeviceInterface: (deviceId: number, data: { ip: string; label?: string | null; vlan_id?: number | null }) =>
    request<DeviceInterface>(`/api/devices/${deviceId}/interfaces`, { method: 'POST', body: JSON.stringify(data) }),
  removeDeviceInterface: (deviceId: number, interfaceId: number) =>
    request<void>(`/api/devices/${deviceId}/interfaces/${interfaceId}`, { method: 'DELETE' }),
  getMergeSuggestions: () => request<MergeSuggestion[]>('/api/interfaces/suggestions'),
  getGateways: () => request<GatewayEntry[]>('/api/network/gateways'),

  // Services
  addService: (deviceId: number, data: Partial<Service>) =>
    request<Service>(`/api/devices/${deviceId}/services`, { method: 'POST', body: JSON.stringify(data) }),
  updateService: (serviceId: number, data: Partial<Service>) =>
    request<Service>(`/api/services/${serviceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteService: (serviceId: number) => request<void>(`/api/services/${serviceId}`, { method: 'DELETE' }),

  // Groups
  getGroups: () => request<DeviceGroup[]>('/api/groups'),
  createGroup: (data: Partial<DeviceGroup>) =>
    request<DeviceGroup>('/api/groups', { method: 'POST', body: JSON.stringify(data) }),
  updateGroup: (id: number, data: Partial<DeviceGroup>) =>
    request<DeviceGroup>(`/api/groups/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteGroup: (id: number) => request<void>(`/api/groups/${id}`, { method: 'DELETE' }),

  // Scanner
  getSubnets: () => request<SubnetInfo[]>('/api/scanner/subnets'),
  getScanStatus: () => request<ScanProgress>('/api/scanner/status'),
  startDashboardScan: (data: { subnets: string[] }) =>
    request<{ status: string }>('/api/scanner/start-dashboard', { method: 'POST', body: JSON.stringify(data) }),
  startScan: (data: Partial<ScanRequest>) =>
    request<{ status: string }>('/api/scanner/start', { method: 'POST', body: JSON.stringify(data) }),
  stopScan: () => request<{ status: string }>('/api/scanner/stop', { method: 'POST' }),
  getDiscoveredHosts: () => request<DiscoveredHost[]>('/api/scanner/discovered'),

  // Network & Topology
  getSubnetsList: () => request<Subnet[]>('/api/network/subnets'),
  createSubnet: (data: Partial<Subnet>) =>
    request<Subnet>('/api/network/subnets', { method: 'POST', body: JSON.stringify(data) }),
  updateSubnet: (id: number, data: Partial<Subnet>) =>
    request<Subnet>(`/api/network/subnets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSubnet: (id: number) => request<void>(`/api/network/subnets/${id}`, { method: 'DELETE' }),
  getRacks: () => request<Rack[]>('/api/topology/racks'),
  createRack: (data: Partial<Rack>) =>
    request<Rack>('/api/topology/racks', { method: 'POST', body: JSON.stringify(data) }),
  deleteRack: (id: number) => request<void>(`/api/topology/racks/${id}`, { method: 'DELETE' }),
  getTopologyLinks: () => request<TopologyLink[]>('/api/topology/links'),

  // Health
  getHealthOverview: (period: '24h' | '7d' | '30d' = '24h') =>
    request<HealthOverviewResponse>(`/api/health/overview?period=${period}`),
  getDeviceHealthDetail: (deviceId: number, period: '24h' | '7d' | '30d' = '24h') =>
    request<DeviceHealthDetailResponse>(`/api/health/device/${deviceId}?period=${period}`),

  // Agent & Telemetry
  getAgentsOverview: () =>
    request<{
      agents: AgentSummary[];
      total_agents: number;
      active_agents: number;
      total_data_points: number;
      avg_cpu: number;
      avg_ram: number;
    }>('/api/agent/overview'),
  getGlobalMetrics: () => request<{ history: GlobalMetricPoint[] }>('/api/agent/global-metrics'),
  getAgentStatus: (deviceId: number) =>
    request<{ device_id: number; is_installed: boolean; is_active: boolean; agent_version?: string; last_seen?: string }>(
      `/api/agent/status/${deviceId}`
    ),
  getAgentMetrics: (deviceId: number, limit?: number, range?: string) => {
    const query: string[] = [];
    if (limit !== undefined) query.push(`limit=${limit}`);
    if (range !== undefined) query.push(`range=${range}`);
    const qs = query.length > 0 ? `?${query.join('&')}` : '';
    return request<{
      device_id: number;
      snapshots: AgentSnapshot[];
      retention_days?: number;
      available_ranges?: string[];
    }>(`/api/agent/metrics/${deviceId}${qs}`);
  },
  getAgentConfig: (deviceId: number) =>
    request<{
      interval: number;
      disk_paths: string[];
      enable_temp: boolean;
      enable_patch_check: boolean;
      enable_scanner_relay: boolean;
    }>(`/api/agent/config/${deviceId}`),
  updateAgentConfig: (
    deviceId: number,
    data: {
      interval?: number;
      disk_paths?: string[];
      enable_temp?: boolean;
      enable_patch_check?: boolean;
      enable_scanner_relay?: boolean;
    }
  ) =>
    request<{
      interval: number;
      disk_paths: string[];
      enable_temp: boolean;
      enable_patch_check: boolean;
      enable_scanner_relay: boolean;
    }>(`/api/agent/config/${deviceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  createAgentEnrollment: (deviceId: number) =>
    request<{ code: string; expires_in: number }>(`/api/agent/enroll/${deviceId}`, { method: 'POST' }),
  adoptAgent: (deviceId: number) => request<{ status: string }>(`/api/agent/adopt/${deviceId}`, { method: 'POST' }),

  // Settings & Auth Tokens
  getSettings: () => request<Record<string, string>>('/api/settings'),
  updateSettings: (settings: Record<string, string>) =>
    request<{ status: string }>('/api/settings', { method: 'POST', body: JSON.stringify(settings) }),
  getApiTokens: () => request<ApiTokenResponse[]>('/api/auth/tokens'),
  createApiToken: (name: string) =>
    request<ApiTokenCreated>('/api/auth/tokens', { method: 'POST', body: JSON.stringify({ name }) }),
  deleteApiToken: (id: number) => request<{ status: string }>(`/api/auth/tokens/${id}`, { method: 'DELETE' }),
};

export function createScanSocket(onMessage: (data: ScanProgress) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let token = localStorage.getItem('gravitylan_token');
  if (token === 'undefined') token = null;
  token = token || '';
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/scanner/ws?token=${token}`);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // Ignore malformed messages
    }
  };
  return ws;
}

export function createMetricsSocket(deviceId: number, onMessage: (data: unknown) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let token = localStorage.getItem('gravitylan_token');
  if (token === 'undefined') token = null;
  token = token || '';
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/agent/ws/${deviceId}?token=${token}`);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // Ignore malformed messages
    }
  };
  return ws;
}
