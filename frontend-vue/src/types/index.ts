/** Core TypeScript interfaces matching the backend Pydantic schemas. */

export interface Service {
  id: number;
  name: string;
  protocol: string;
  port: number;
  url_template: string;
  color: string | null;
  is_auto_detected: boolean;
  sort_order: number;
  is_up: boolean;
  last_checked: string | null;
  ssl_expiry_days?: number | null;
  ignore_ssl?: boolean;
}

export interface Device {
  id: number;
  ip: string;
  mac: string | null;
  hostname: string | null;
  display_name: string;
  device_type: string;
  device_subtype: string;
  vendor?: string;
  group_id: number | null;
  icon: string | null;
  sort_order: number;
  is_pinned: boolean;
  is_hidden: boolean;
  x: number | null;
  y: number | null;
  w: number | null;
  h: number | null;
  notes: string | null;
  first_seen: string;
  last_seen: string;
  is_online: boolean;
  alert_offline?: boolean;
  status_changed_at: string;
  is_reserved: boolean;
  virtual_type: 'docker' | 'lxc' | 'vm' | null;
  has_agent: boolean;
  has_pending_token?: boolean;
  agent_info?: {
    agent_version: string | null;
    latest_version: string | null;
    metrics?: {
      cpu_usage: number;
      memory_usage: number;
      disk_usage: number;
    };
  };
  services: Service[];
  old_ip: string | null;
  ip_changed_at: string | null;
  parent_id: number | null;
  parent_name?: string | null;
  rack_id: number | null;
  rack_unit: number | null;
  rack_height: number;
  topology_x: number | null;
  topology_y: number | null;
  max_ports?: number | null;
  topology_config?: string | null;
  is_wlan: boolean;
  is_ap: boolean;
  is_host: boolean;
  subnet_id?: number | null;
  subnet_name?: string | null;
  subnet_vlan_id?: number | null;
  interfaces?: DeviceInterface[];
}

export interface DeviceInterface {
  id: number;
  device_id: number;
  ip: string;
  mac: string | null;
  subnet_id: number | null;
  subnet_name: string | null;
  subnet_cidr: string | null;
  vlan_id: number | null;
  label: string | null;
  is_online: boolean;
  last_seen: string | null;
  first_seen: string | null;
}

export interface DeviceGroup {
  id: number;
  name: string;
  icon: string | null;
  color: string | null;
  sort_order: number;
  is_default: boolean;
  device_count: number;
}

export interface SubnetInfo {
  interface_name: string;
  ip_address: string;
  subnet: string;
  netmask: string;
  is_up: boolean;
  is_virtual?: boolean;
}

export interface Subnet {
  id: number;
  cidr: string;
  name: string;
  dns_server: string | null;
  is_enabled: boolean;
  is_direct_l2?: boolean;
  interface_name?: string | null;
  is_agent_probe?: boolean;
  probe_device_name?: string | null;
  probe_device_ip?: string | null;
  gateway_ip?: string | null;
  vlan_id?: number | null;
  gateway_suggestion?: string | null;
  gateway_source?: 'detected' | 'suggested' | null;
}

export interface ScanProgress {
  status: 'idle' | 'running' | 'discovering' | 'identifying' | 'devices_updated' | 'completed' | 'failed' | 'cancelled';
  current_subnet: string;
  hosts_scanned: number;
  hosts_total: number;
  devices_found: number;
  message: string;
  timestamp: string;
}

export interface ScanRequest {
  subnets: string[];
  ports?: number[];
  mode?: 'gentle' | 'fast';
}

export interface DiscoveredHost {
  id: number;
  ip: string;
  mac: string | null;
  hostname: string | null;
  custom_name: string | null;
  vendor: string | null;
  is_online: boolean;
  is_monitored: boolean;
  is_reserved: boolean;
  ports?: number[];
  first_seen: string;
  last_seen: string;
}

export interface AgentSummary {
  device_id: number;
  hostname: string;
  ip: string;
  is_online: boolean;
  has_pending_token?: boolean;
  agent_version: string | null;
  last_seen: string | null;
  cpu_usage: number;
  ram_usage: number;
  temp: number | null;
  uptime_pct: number;
  uptime_history: number[];
  metrics_count: number;
  patch_available: number;
  patch_security: number;
  patch_manager: string | null;
  reboot_required: boolean;
  major_upgrade_available: string | null;
}

export interface ApiTokenResponse {
  id: number;
  name: string;
  prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiTokenCreated extends ApiTokenResponse {
  token: string;
}

export * from './health';
