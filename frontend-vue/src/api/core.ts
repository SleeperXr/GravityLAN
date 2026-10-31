/** HTTP client for the GravityLAN backend. Started as a copy of the React UI's client (frontend/src/api). */

/** What a 401 and a logout do. The Vue UI under /frontend-vue/ replaces both with its own login screen. */
export const authHandlers = {
  onUnauthorized: () => {
    // Redirect to login if unauthorized and not already on auth/setup pages
    if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/setup')) {
      window.location.href = '/login';
    }
  },
  onLoggedOut: () => {
    window.location.href = '/login';
  },
};

/** An API error that keeps the HTTP status, so callers can tell 401/404/409 apart. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

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

  if (response.status === 401) authHandlers.onUnauthorized();

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(formatErrorDetail(error.detail) || `API Error: ${response.status}`, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

/** FastAPI sends `detail` as a string, or as a list of `{ msg }` objects for validation errors (422). */
function formatErrorDetail(detail: unknown): string {
  if (Array.isArray(detail)) return detail.map((item) => item?.msg ?? String(item)).join('; ');
  return typeof detail === 'string' ? detail : '';
}

/** How long each measurement tier is kept (raw rows in hours, rollups in days). */
export interface TelemetryRetention {
  raw_hours: number;
  hourly_days: number;
  daily_days: number;
}

export interface TelemetryTableStats {
  rows: number;
  oldest: string | null;
  newest: string | null;
}

/** Settings > Measurement data: sizes of both databases, rows per table, retention. */
export interface TelemetryStatus {
  sizes: { inventory_bytes: number; telemetry_bytes: number; telemetry_free_bytes: number };
  tables: Record<'device_health_samples' | 'device_metrics' | 'device_health_rollups' | 'device_metrics_rollups', TelemetryTableStats>;
  retention: TelemetryRetention;
  limits: Record<keyof TelemetryRetention, { min: number; max: number; default: number }>;
}

export type TelemetryPurge =
  | { scope: 'older_than'; older_than_days: number }
  | { scope: 'device'; device_id: number }
  | { scope: 'all' };

/** Result of a backup import. */
export type BackupImportResult = {
  status: string;
  message: string;
  /** Agents of devices whose id names another device after the import; they must be enrolled again */
  agent_tokens_revoked?: number;
  reassigned_devices?: number;
};

/** Result of an agent deploy/uninstall over SSH. */
export type AgentSshResult = {
  status: string;
  message: string;
  /** "host_key_changed": refused before logging in, the host presented another SSH key than stored */
  error_code?: string | null;
};

export const api = {
  // Setup
  getSetupStatus: () =>
    request<{ is_setup_complete: boolean; device_count: number; version?: string; build?: string; agent_version?: string }>('/api/setup/status'),
  // Signs the admin in via session cookie when a password is set
  completeSetup: (data?: { dns_server?: string; admin_password?: string; subnets?: string[] }) =>
    request<{ status: string; devices_adopted: number }>('/api/setup/complete', { method: 'POST', body: JSON.stringify(data || {}) })
      .then((res) => {
        // Same as a password login: the session cookie replaces any token left by older versions
        localStorage.removeItem('gravitylan_token');
        return res;
      }),

  // Scanner
  getSubnets: () => request<import('../types').SubnetInfo[]>('/api/scanner/subnets'),
  startScan: (data: Partial<import('../types').ScanRequest> & { dns_server?: string }) =>
    request<{ status: string }>('/api/scanner/start', { method: 'POST', body: JSON.stringify(data) }),
  startDashboardScan: (data: { subnets: string[] }) => 
    request<{ status: string }>('/api/scanner/start-dashboard', { method: 'POST', body: JSON.stringify(data) }),
  stopScan: () => request<{ status: string }>('/api/scanner/stop', { method: 'POST' }),
  getScanStatus: () => request<import('../types').ScanProgress>('/api/scanner/status'),
  getDiscoveredHosts: () => request<import('../types').DiscoveredHost[]>('/api/scanner/discovered'),
  scanIp: (ip: string) => request<import('../types').DiscoveredHost>(`/api/scanner/scan-ip?ip=${ip}`),
  liveDiscovery: (data: { subnets: string[] }) =>
    request<import('../types').DiscoveredHost[]>(`/api/scanner/live-discovery?subnets=${data.subnets.join(',')}`),
  patchDiscoveredHost: (id: number, data: { custom_name?: string; is_monitored?: boolean; is_reserved?: boolean }) =>
    request<import('../types').DiscoveredHost>(`/api/scanner/discovered/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  refreshDiscoveredHost: (id: number) =>
    request<import('../types').DiscoveredHost>(`/api/scanner/discovered/${id}/refresh-info`, { method: 'POST' }),
  deleteDiscoveredHost: (id: number) =>
    request<{ status: string; message: string }>(`/api/scanner/discovered/${id}`, { method: 'DELETE' }),
  quickSubnetScan: (subnets: string) =>
    request<{ status: string; hosts_found: number }>(`/api/scanner/quick-subnet-scan?subnets=${subnets}`, { method: 'POST' }),

  // Devices
  getDevices: (includeHidden = false) =>
    request<import('../types').Device[]>(includeHidden ? '/api/devices?include_hidden=true' : '/api/devices'),
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

  // Interfaces (further addresses of one device) and subnet gateways
  getDeviceInterfaces: (deviceId: number) =>
    request<import('../types').DeviceInterface[]>(`/api/devices/${deviceId}/interfaces`),
  addDeviceInterface: (deviceId: number, data: { ip: string; label?: string | null; vlan_id?: number | null }) =>
    request<import('../types').DeviceInterface>(`/api/devices/${deviceId}/interfaces`, { method: 'POST', body: JSON.stringify(data) }),
  mergeIntoDevice: (deviceId: number, data: { source_device_id: number } | { ip: string }) =>
    request<import('../types').DeviceInterface>(`/api/devices/${deviceId}/interfaces/merge`, { method: 'POST', body: JSON.stringify(data) }),
  updateDeviceInterface: (deviceId: number, interfaceId: number, data: { label?: string | null; vlan_id?: number | null }) =>
    request<import('../types').DeviceInterface>(`/api/devices/${deviceId}/interfaces/${interfaceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  removeDeviceInterface: (deviceId: number, interfaceId: number) =>
    request<void>(`/api/devices/${deviceId}/interfaces/${interfaceId}`, { method: 'DELETE' }),
  getMergeSuggestions: () => request<import('../types').MergeSuggestion[]>('/api/interfaces/suggestions'),
  dismissMergeSuggestion: (data: { target_id: number; kind: 'device' | 'discovered'; candidate_ip: string }) =>
    request<void>('/api/interfaces/suggestions/dismiss', { method: 'POST', body: JSON.stringify(data) }),
  getGateways: () => request<import('../types').GatewayEntry[]>('/api/network/gateways'),

  // Services
  addService: (deviceId: number, data: Partial<import('../types').Service>) => request<import('../types').Service>(`/api/devices/${deviceId}/services`, { method: 'POST', body: JSON.stringify(data) }),
  updateService: (serviceId: number, data: Partial<import('../types').Service>) => request<import('../types').Service>(`/api/services/${serviceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
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
  getThemeSettings: () => request<Record<string, string>>('/api/settings').then(s => {
    // Filter only theme-related settings to keep it clean
    const theme: Record<string, string> = {};
    for (const k in s) {
      if (k.startsWith('theme.')) theme[k] = s[k];
    }
    return theme;
  }),
  updateSettings: (settings: Record<string, string>) => 
    request<{ status: string }>('/api/settings', { method: 'POST', body: JSON.stringify(settings) }),
  resetDatabase: () => request<{status: string, message: string}>('/api/settings/reset-db', { method: 'POST' }),

  // Measurement data (separate telemetry database)
  getTelemetryStatus: () => request<TelemetryStatus>('/api/settings/telemetry'),
  updateTelemetryRetention: (retention: TelemetryRetention) =>
    request<TelemetryStatus>('/api/settings/telemetry/retention', { method: 'PUT', body: JSON.stringify(retention) }),
  purgeTelemetry: (purge: TelemetryPurge) =>
    request<TelemetryStatus & { deleted: Record<string, number> }>('/api/settings/telemetry/purge', {
      method: 'POST',
      body: JSON.stringify(purge),
    }),
  
  // Backup
  exportBackup: () => fetch('/api/backup/export').then(res => res.json()),
  importBackup: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return fetch('/api/backup/import', { method: 'POST', body: formData }).then(async (res) => {
      const body = await res.json().catch(() => ({}));
      // A refused or rolled-back import must not read as success
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : res.statusText);
      return body as BackupImportResult;
    });
  },

  // Agent
  deployAgent: (deviceId: number, data: import('../types').AgentSshLogin) =>
    request<AgentSshResult & { agent_version?: string }>(`/api/agent/deploy/${deviceId}`, { method: 'POST', body: JSON.stringify(data) }),
  uninstallAgent: (deviceId: number, data: import('../types').AgentSshLogin) =>
    request<AgentSshResult>(`/api/agent/uninstall/${deviceId}`, { method: 'POST', body: JSON.stringify(data) }),
  createAgentEnrollment: (deviceId: number) =>
    request<{ code: string; expires_in: number; server_url?: string; insecure?: boolean; insecure_allowed?: boolean }>(
      `/api/agent/enroll/${deviceId}`, { method: 'POST' },
    ),
  getAgentStatus: (deviceId: number) =>
    request<{ device_id: number; is_installed: boolean; is_active: boolean; agent_version?: string; last_seen?: string }>(`/api/agent/status/${deviceId}`),
  getAgentMetrics: (deviceId: number, limit?: number, range?: string) => {
    const query = [];
    if (limit !== undefined) query.push(`limit=${limit}`);
    if (range !== undefined) query.push(`range=${range}`);
    const qs = query.length > 0 ? `?${query.join('&')}` : '';
    return request<{ 
      device_id: number; 
      snapshots: import('../types').AgentSnapshot[];
      retention_days?: number;
      available_ranges?: string[];
    }>(`/api/agent/metrics/${deviceId}${qs}`);
  },

  getAgentConfig: (deviceId: number) =>
    request<{ interval: number; disk_paths: string[]; enable_temp: boolean; enable_patch_check: boolean; enable_scanner_relay: boolean }>(`/api/agent/config/${deviceId}`),
  updateAgentConfig: (deviceId: number, data: { interval?: number; disk_paths?: string[]; enable_temp?: boolean; enable_patch_check?: boolean; enable_scanner_relay?: boolean }) =>
    request<{ interval: number; disk_paths: string[]; enable_temp: boolean; enable_patch_check: boolean; enable_scanner_relay: boolean }>(`/api/agent/config/${deviceId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  adoptAgent: (deviceId: number) => 
    request<{ status: string }>(`/api/agent/adopt/${deviceId}`, { method: 'POST' }),
  queryAgentPatches: (deviceId: number, data: { ssh_user: string; ssh_password?: string; sudo_password?: string; ssh_key?: string; ssh_port?: number; key_id?: number | null; key_passphrase?: string; profile_id?: number | null }) =>
    request<{
      device_id: number;
      patch_manager: string | null;
      packages: { package: string; current_version: string; new_version: string; repo?: string }[];
      major_upgrade_available: string | null;
    }>(`/api/agent/patches/${deviceId}/query`, { method: 'POST', body: JSON.stringify(data) }),
  prepareAgentPatch: (deviceId: number, data: { ssh_user: string; ssh_password?: string; sudo_password?: string; ssh_key?: string; ssh_port?: number; mode: string; key_id?: number | null; key_passphrase?: string; profile_id?: number | null }) =>
    request<{ patch_token: string }>(`/api/agent/patches/${deviceId}/prepare`, { method: 'POST', body: JSON.stringify(data) }),
  getAgentsOverview: () => 
    request<{
      agents: import('../types').AgentSummary[];
      total_agents: number;
      active_agents: number;
      total_data_points: number;
      avg_cpu: number;
      avg_ram: number;
    }>('/api/agent/overview'),
  getGlobalMetrics: () => 
    request<{ history: import('../types').GlobalMetricPoint[] }>('/api/agent/global-metrics'),

  // Network (Subnets)
  getSubnetsList: () => request<import('../types').Subnet[]>('/api/network/subnets'),
  createSubnet: (data: Partial<import('../types').Subnet>) => request<import('../types').Subnet>('/api/network/subnets', { method: 'POST', body: JSON.stringify(data) }),
  updateSubnet: (id: number, data: Partial<import('../types').Subnet>) => request<import('../types').Subnet>(`/api/network/subnets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSubnet: (id: number) => request<void>(`/api/network/subnets/${id}`, { method: 'DELETE' }),

  // Import subnets/VLANs from a router
  getRouterSources: () => request<import('../types').RouterSource[]>('/api/network/router-import/sources'),
  deleteRouterSource: (provider: import('../types').RouterImportProvider) =>
    request<{ status: string }>(`/api/network/router-import/sources/${provider}`, { method: 'DELETE' }),
  previewRouterImport: (data: import('../types').RouterImportRequest) =>
    request<import('../types').RouterImportPreview>('/api/network/router-import/preview', { method: 'POST', body: JSON.stringify(data) }),
  applyRouterImport: (networks: import('../types').RouterImportApplyItem[]) =>
    request<import('../types').RouterImportApplyResult>('/api/network/router-import/apply', { method: 'POST', body: JSON.stringify({ networks }) }),

  // Topology
  getRacks: () => request<import('../types').Rack[]>('/api/topology/racks'),
  createRack: (data: Partial<import('../types').Rack>) => request<import('../types').Rack>('/api/topology/racks', { method: 'POST', body: JSON.stringify(data) }),
  updateRack: (id: number, data: Partial<import('../types').Rack>) => request<import('../types').Rack>('/api/topology/racks/' + id, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteRack: (id: number) => request<void>(`/api/topology/racks/${id}`, { method: 'DELETE' }),
  getCabling: () => request<import('../types').RackCabling>('/api/topology/cabling'),
  createRackItem: (data: Partial<import('../types').RackItem> & { rack_id: number; name: string; port_count?: number; port_kind?: string }) =>
    request<import('../types').RackItem>('/api/topology/rack-items', { method: 'POST', body: JSON.stringify(data) }),
  updateRackItem: (id: number, data: Partial<import('../types').RackItem>) =>
    request<import('../types').RackItem>(`/api/topology/rack-items/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteRackItem: (id: number) => request<void>(`/api/topology/rack-items/${id}`, { method: 'DELETE' }),
  setPorts: (data: { owner_type: 'device' | 'item'; owner_id: number; count: number; kind: string; side?: 'front' | 'rear' }) =>
    request<import('../types').RackPort[]>('/api/topology/ports', { method: 'PUT', body: JSON.stringify(data) }),
  createCable: (data: { a_port_id: number; b_port_id: number; cable?: string; color?: string | null; notes?: string | null }) =>
    request<import('../types').RackCable>('/api/topology/rack-cables', { method: 'POST', body: JSON.stringify(data) }),
  updateCable: (id: number, data: Partial<import('../types').RackCable>) =>
    request<import('../types').RackCable>(`/api/topology/rack-cables/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteCable: (id: number) => request<void>(`/api/topology/rack-cables/${id}`, { method: 'DELETE' }),
  getTopologyLinks: () => request<import('../types').TopologyLink[]>('/api/topology/links'),
  getTopologyMap: async () => {
    const [devices, links] = await Promise.all([
      request<import('../types').Device[]>('/api/devices?include_hidden=false'),
      request<import('../types').TopologyLink[]>('/api/topology/links'),
    ]);
    return { devices, links };
  },
  createTopologyLink: (data: Partial<import('../types').TopologyLink>) => request<import('../types').TopologyLink>('/api/topology/links', { method: 'POST', body: JSON.stringify(data) }),
  updateTopologyLink: (id: number, data: Partial<import('../types').TopologyLink>) => request<import('../types').TopologyLink>(`/api/topology/links/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteTopologyLink: (id: number) => request<void>(`/api/topology/links/${id}`, { method: 'DELETE' }),

  // API Tokens
  getApiTokens: () => request<import('../types').ApiTokenResponse[]>('/api/auth/tokens'),
  getAuditEvents: (params: { action?: string; result?: string; q?: string; before_id?: number; limit?: number } = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value));
    const qs = query.toString();
    return request<import('../components/logstream/auditModel').AuditPage>(`/api/audit${qs ? `?${qs}` : ''}`);
  },
  createApiToken: (name: string) => request<import('../types').ApiTokenCreated>('/api/auth/tokens', { method: 'POST', body: JSON.stringify({ name }) }),
  deleteApiToken: (id: number) => request<{ status: string; message: string }>(`/api/auth/tokens/${id}`, { method: 'DELETE' }),

  // SSH terminal
  getSshStatus: () => request<import('../types').SshStatus>('/api/ssh/status'),
  getSshKeys: () => request<import('../types').SshKey[]>('/api/ssh/keys'),
  createSshKey: (data: { name: string; private_key: string; passphrase?: string }) =>
    request<import('../types').SshKey>('/api/ssh/keys', { method: 'POST', body: JSON.stringify(data) }),
  generateSshKey: (name: string) =>
    request<import('../types').SshKey>('/api/ssh/keys/generate', { method: 'POST', body: JSON.stringify({ name }) }),
  deleteSshKey: (id: number) => request<{ status: string }>(`/api/ssh/keys/${id}`, { method: 'DELETE' }),
  getSshProfiles: () => request<import('../types').SshProfile[]>('/api/ssh/profiles'),
  createSshProfile: (data: import('../types').SshProfileInput) =>
    request<import('../types').SshProfile>('/api/ssh/profiles', { method: 'POST', body: JSON.stringify(data) }),
  updateSshProfile: (id: number, data: import('../types').SshProfileInput) =>
    request<import('../types').SshProfile>(`/api/ssh/profiles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSshProfile: (id: number) => request<{ status: string }>(`/api/ssh/profiles/${id}`, { method: 'DELETE' }),
  getSshHistory: () => request<import('../types').SshHistoryEntry[]>('/api/ssh/history'),
  deleteSshHistory: (id: number) => request<{ status: string }>(`/api/ssh/history/${id}`, { method: 'DELETE' }),
  getSshKnownHosts: () => request<import('../types').SshKnownHost[]>('/api/ssh/known-hosts'),
  deleteSshKnownHost: (id: number) => request<{ status: string }>(`/api/ssh/known-hosts/${id}`, { method: 'DELETE' }),
  prepareSshSession: (data: import('../types').SshSessionRequest) =>
    request<{ ticket: string; label: string; expires_in: number }>('/api/ssh/sessions/prepare', { method: 'POST', body: JSON.stringify(data) }),

  // Auth
  login: (password: string) =>
    request<{ status: string; token?: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) })
      .then(res => {
        if (res.token) {
          localStorage.setItem('gravitylan_token', res.token);
        } else {
          // Password logins use the session cookie; a token left by older versions would keep the
          // browser "logged in" after the cookie expires, and the SSH terminal accepts the cookie only
          localStorage.removeItem('gravitylan_token');
        }
        return res;
      }),
  logout: () => 
    request<{ status: string }>('/api/auth/logout', { method: 'POST' }).then(() => {
      localStorage.removeItem('gravitylan_token');
      authHandlers.onLoggedOut();
    }),
  checkAuth: () => request<{ status: string }>('/api/auth/check', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    request<{ status: string; other_sessions_ended: number }>('/api/auth/password', {
      method: 'POST', body: JSON.stringify({ current_password, new_password }),
    }),

  // Health Dashboard & Telemetry
  getHealthOverview: (period: '24h' | '7d' | '30d' = '24h') =>
    request<import('../types').HealthOverviewResponse>(`/api/health/overview?period=${period}`),
  getDeviceHealthDetail: (deviceId: number, period: '24h' | '7d' | '30d' = '24h') =>
    request<import('../types').DeviceHealthDetailResponse>(`/api/health/device/${deviceId}?period=${period}`),
};

/** Create a WebSocket connection for scan progress updates. */
export function createScanSocket(onMessage: (data: import('../types').ScanProgress) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let token = localStorage.getItem('gravitylan_token');
  if (token === 'undefined') token = null;
  token = token || '';
  const wsBase = `${protocol}//${window.location.host}`;
  const ws = new WebSocket(`${wsBase}/api/scanner/ws?token=${token}`);

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
export function createMetricsSocket(deviceId: number, onMessage: (data: unknown) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  let token = localStorage.getItem('gravitylan_token');
  if (token === 'undefined') token = null;
  token = token || '';
  const wsBase = `${protocol}//${window.location.host}`;
  const ws = new WebSocket(`${wsBase}/api/agent/ws/${deviceId}?token=${token}`);

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

/**
 * Open the SSH terminal WebSocket for a ticket from api.prepareSshSession.
 * Auth is the session cookie; terminal data is binary, control messages are JSON text.
 */
export function createSshTerminalSocket(ticket: string, cols: number, rows: number): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const params = new URLSearchParams({ ticket, cols: String(cols), rows: String(rows) });
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/ssh/terminal?${params}`);
  ws.binaryType = 'arraybuffer';
  return ws;
}
