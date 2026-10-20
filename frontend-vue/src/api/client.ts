/** API client for GravityUI (Vue 3) sharing the FastAPI backend session cookie. */
import type {
  AgentSummary,
  ApiTokenCreated,
  ApiTokenResponse,
  Device,
  DeviceGroup,
  DeviceHealthDetailResponse,
  DiscoveredHost,
  HealthOverviewResponse,
  ScanProgress,
  ScanRequest,
  Subnet,
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

  getDevices: () => request<Device[]>('/api/devices'),
  getDevice: (id: number) => request<Device>(`/api/devices/${id}`),
  updateDevice: (id: number, data: Partial<Device>) =>
    request<Device>(`/api/devices/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteDevice: (id: number) => request<void>(`/api/devices/${id}`, { method: 'DELETE' }),
  refreshDeviceInfo: (id: number) => request<Device>(`/api/devices/${id}/refresh-info`, { method: 'POST' }),
  refreshServices: (id: number) => request<Device>(`/api/devices/${id}/refresh-services`, { method: 'POST' }),

  getGroups: () => request<DeviceGroup[]>('/api/groups'),

  getScanStatus: () => request<ScanProgress>('/api/scanner/status'),
  startDashboardScan: (data: { subnets: string[] }) =>
    request<{ status: string }>('/api/scanner/start-dashboard', { method: 'POST', body: JSON.stringify(data) }),
  startScan: (data: Partial<ScanRequest>) =>
    request<{ status: string }>('/api/scanner/start', { method: 'POST', body: JSON.stringify(data) }),
  stopScan: () => request<{ status: string }>('/api/scanner/stop', { method: 'POST' }),
  getDiscoveredHosts: () => request<DiscoveredHost[]>('/api/scanner/discovered'),

  getSubnetsList: () => request<Subnet[]>('/api/network/subnets'),
  updateSubnet: (id: number, data: Partial<Subnet>) =>
    request<Subnet>(`/api/network/subnets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  getHealthOverview: (period: '24h' | '7d' | '30d' = '24h') =>
    request<HealthOverviewResponse>(`/api/health/overview?period=${period}`),
  getDeviceHealthDetail: (deviceId: number, period: '24h' | '7d' | '30d' = '24h') =>
    request<DeviceHealthDetailResponse>(`/api/health/device/${deviceId}?period=${period}`),

  getAgentsOverview: () =>
    request<{
      agents: AgentSummary[];
      total_agents: number;
      active_agents: number;
      total_data_points: number;
      avg_cpu: number;
      avg_ram: number;
    }>('/api/agent/overview'),
  adoptAgent: (deviceId: number) => request<{ status: string }>(`/api/agent/adopt/${deviceId}`, { method: 'POST' }),

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
