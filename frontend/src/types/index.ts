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
    /** The agent's latest report as cached by the server; empty until it reports after a restart */
    latest_metrics?: {
      patch_available?: number;
      patch_security?: number;
      reboot_required?: boolean;
      [key: string]: unknown;
    } | null;
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
  /** Subnet of the primary ip (from the configured subnets) */
  subnet_id?: number | null;
  subnet_name?: string | null;
  subnet_vlan_id?: number | null;
  /** Further addresses of this device, e.g. a router's gateway in other VLANs */
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

export type MergeReason = 'same_mac' | 'same_hostname' | 'same_host_key' | 'subnet_gateway';

export interface MergeSuggestion {
  target_id: number;
  target_name: string;
  target_ip: string;
  candidate: {
    kind: 'device' | 'discovered';
    id: number;
    ip: string;
    name: string | null;
    mac: string | null;
    subnet_id: number | null;
    subnet_name: string | null;
    is_online: boolean;
  };
  reasons: MergeReason[];
}

/** The gateway of one configured subnet and who answers on it. */
export interface GatewayEntry {
  subnet_id: number;
  subnet_name: string;
  cidr: string;
  vlan_id: number | null;
  is_enabled: boolean;
  gateway_ip: string | null;
  source: 'configured' | 'detected' | 'suggested' | null;
  device_id: number | null;
  device_name: string | null;
  interface_id: number | null;
  is_primary: boolean;
  is_online: boolean | null;
  last_seen: string | null;
  mac: string | null;
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
  /** Router address in this subnet; empty means detected/suggested (gateway_suggestion) */
  gateway_ip?: string | null;
  vlan_id?: number | null;
  gateway_suggestion?: string | null;
  gateway_source?: 'detected' | 'suggested' | null;
}

/** How a router is asked for its networks: read-only SNMP (most routers) or the UniFi console API. */
export type RouterImportProvider = 'snmp' | 'unifi';

/** A saved router connection; secrets are never sent back, only which ones are stored. */
export interface RouterSource {
  provider: RouterImportProvider;
  host: string;
  port: number | null;
  options: Record<string, string | null>;
  stored_secrets: string[];
}

export interface RouterImportRequest {
  provider: RouterImportProvider;
  host: string;
  port?: number | null;
  options?: Record<string, string | null>;
  /** Empty values fall back to the stored secrets of the same router */
  secrets?: Record<string, string>;
  remember?: boolean;
}

export interface RouterNetworkPreview {
  cidr: string;
  name: string | null;
  gateway_ip: string | null;
  vlan_id: number | null;
  interface: string | null;
  /** new: not configured; update: configured, empty gateway/VLAN gets filled; exists: nothing to add; too_large: bigger than a /16 */
  status: 'new' | 'update' | 'exists' | 'too_large';
  fills: ('gateway_ip' | 'vlan_id')[];
  existing_name: string | null;
}

export interface RouterImportPreview {
  /** confirm_certificate: the console's TLS certificate fingerprint must be confirmed first */
  status: 'ok' | 'confirm_certificate';
  provider: RouterImportProvider;
  host: string;
  networks: RouterNetworkPreview[];
  fingerprint?: string | null;
  reason?: 'untrusted_certificate' | 'certificate_mismatch' | null;
  message?: string | null;
}

export interface RouterImportApplyItem {
  cidr: string;
  name?: string | null;
  gateway_ip?: string | null;
  vlan_id?: number | null;
}

export interface RouterImportApplyResult {
  added: string[];
  updated: string[];
  unchanged: string[];
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
  ports?: number[];
  first_seen: string;
  last_seen: string;
}
export interface AgentSnapshot {
  id: number;
  device_id: number;
  cpu_percent: number;
  ram_used_mb: number;
  ram_total_mb: number;
  ram_percent: number;
  disk_json: string | null;
  temperature: number | null;
  net_json: string | null;
  timestamp: string;
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

export interface GlobalMetricPoint {
  timestamp: string;
  avg_cpu: number;
  avg_ram: number;
  data_points: number;
}

export interface Rack {
  id: number;
  name: string;
  units: number;
  width: number;
  notes: string | null;
}

/** Rack equipment outside the network inventory (switch without management, UPS, patch panel, blank, ...). */
export interface RackItem {
  id: number;
  rack_id: number;
  name: string;
  kind: string;
  rack_unit: number | null;
  rack_height: number;
  notes: string | null;
}

/** A port of a device or of a rack item; exactly one of device_id and rack_item_id is set. */
export interface RackPort {
  id: number;
  device_id: number | null;
  rack_item_id: number | null;
  number: number;
  kind: string;
}

/** A physical cable between two ports of the rack. */
export interface RackCable {
  id: number;
  a_port_id: number;
  b_port_id: number;
  cable: string;
  color: string | null;
  notes: string | null;
  created_at: string;
}

export interface RackCabling {
  items: RackItem[];
  ports: RackPort[];
  cables: RackCable[];
}

export interface TopologyLink {
  id: number;
  source_id: number;
  target_id: number;
  source_handle: string | null;
  target_handle: string | null;
  link_type: string;
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

// --- SSH terminal ---

export type SshAuthMethod = 'key' | 'password' | 'ask';

export interface SshKey {
  id: number;
  name: string;
  key_type: string;
  fingerprint: string;
  public_key: string;
  has_passphrase: boolean;
  created_at: string | null;
  last_used_at: string | null;
}

export interface SshProfile {
  id: number;
  name: string;
  device_id: number | null;
  device_name: string | null;
  host: string | null;
  target_host: string | null;
  port: number;
  username: string;
  auth_method: SshAuthMethod;
  key_id: number | null;
  key_name: string | null;
  has_password: boolean;
  created_at: string | null;
  last_connected_at: string | null;
}

export interface SshProfileInput {
  name?: string;
  device_id?: number | null;
  host?: string | null;
  port?: number;
  username?: string;
  auth_method?: SshAuthMethod;
  key_id?: number | null;
  password?: string;
}

export interface SshKnownHost {
  id: number;
  host: string;
  port: number;
  key_type: string;
  fingerprint: string;
  first_seen: string | null;
  last_seen: string | null;
}

export interface SshStatus {
  vault_key_source: 'env' | 'file';
  active_sessions: number;
  max_sessions: number;
  idle_timeout_minutes: number;
}

/** What to connect to: a saved profile (plus a password for 'ask' profiles) or an ad-hoc target. */
/** A recent ad-hoc connection (no password stored). */
export interface SshHistoryEntry {
  id: number;
  label: string;
  device_id: number | null;
  device_name: string | null;
  host: string | null;
  target_host: string | null;
  port: number;
  username: string;
  auth_method: 'key' | 'password';
  key_id: number | null;
  key_name: string | null;
  last_used_at: string | null;
}

/** SSH login for agent deploy/uninstall: typed-in credentials, or a saved key connection of the device. */
export type AgentSshLogin =
  | { ssh_user: string; ssh_password?: string; ssh_key?: string; ssh_port?: number; key_id?: number | null; key_passphrase?: string }
  | { profile_id: number; sudo_password?: string; ssh_port?: number };

export interface SshSessionRequest {
  profile_id?: number;
  device_id?: number;
  host?: string;
  port?: number;
  username?: string;
  key_id?: number;
  password?: string;
}

export * from './health';
