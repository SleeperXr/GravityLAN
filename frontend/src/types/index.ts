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
  status_changed_at: string;
  virtual_type: 'docker' | 'lxc' | 'vm' | null;
  has_agent: boolean;
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
  rack_id: number | null;
  rack_unit: number | null;
  rack_height: number;
  topology_x: number | null;
  topology_y: number | null;
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
}

export interface Subnet {
  id: number;
  cidr: string;
  name: string;
  dns_server: string | null;
  is_enabled: boolean;
}

export interface ScanProgress {
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled';
  current_subnet: string;
  hosts_scanned: number;
  hosts_total: number;
  devices_found: number;
  message: string;
  timestamp: string;
}

export interface DeviceHistoryResponse {
  id: number;
  device_id: number;
  service_id: number | null;
  status: string;
  message: string | null;
  timestamp: string;
}

export interface ScanRequest {
  subnets: string[];
  ports?: number[];
  mode?: 'gentle' | 'fast';
}

export interface SetupStatus {
  is_setup_complete: boolean;
  device_count: number;
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
  first_seen: string;
  last_seen: string;
}
