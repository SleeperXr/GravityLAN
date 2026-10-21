/** Agent metrics in one shape (ported from React Dashboard/DeviceMetrics.tsx). */

export interface DiskUsage {
  path: string;
  total_gb: number;
  used_gb: number;
  percent: number;
}

export interface MetricsData {
  cpu_percent: number;
  ram: { used_mb: number; total_mb: number; percent: number };
  disk: DiskUsage[];
  temperature: number | null;
  network: Record<string, { rx_bytes_sec: number; tx_bytes_sec: number }>;
  timestamp: string;
}

export type RawSample = Partial<MetricsData> & {
  ram_used_mb?: number;
  ram_total_mb?: number;
  ram_percent?: number;
  disk_json?: string | null;
  net_json?: string | null;
};

function parseJson<T>(raw: string | null | undefined): T | null {
  try {
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/**
 * Live WebSocket/agent payloads are nested (`ram.percent`, `disk[]`), stored history rows
 * are flat (`ram_percent`, `disk_json`).
 */
export function toMetricsData(sample: RawSample | null | undefined): MetricsData {
  if (sample?.ram) return sample as MetricsData;
  return {
    cpu_percent: sample?.cpu_percent ?? 0,
    ram: { used_mb: sample?.ram_used_mb ?? 0, total_mb: sample?.ram_total_mb ?? 0, percent: sample?.ram_percent ?? 0 },
    disk: parseJson<DiskUsage[]>(sample?.disk_json) ?? [],
    temperature: sample?.temperature ?? null,
    network: parseJson<MetricsData['network']>(sample?.net_json) ?? {},
    timestamp: sample?.timestamp ?? '',
  };
}

/** WebSocket messages are wrapped: { type: 'metrics', data: { ... } } */
export function unwrap(msg: unknown): RawSample {
  const m = msg as { type?: string; data?: RawSample } & RawSample;
  return m && m.type === 'metrics' && m.data ? m.data : m;
}

export type MeterTone = 'ok' | 'warn' | 'danger';

/** Calm while normal; amber/red only when a threshold is crossed. */
export function meterTone(value: number, warnAt: number, dangerAt: number): MeterTone {
  if (value >= dangerAt) return 'danger';
  if (value >= warnAt) return 'warn';
  return 'ok';
}

export function formatBps(bytesPerSec: number): string {
  if (bytesPerSec >= 1_000_000) return `${(bytesPerSec / 1_000_000).toFixed(1)} MB/s`;
  if (bytesPerSec >= 1_000) return `${(bytesPerSec / 1_000).toFixed(0)} KB/s`;
  return `${bytesPerSec} B/s`;
}

/** The fullest disk: the one worth noticing on a card. */
export function fullestDisk(disks: DiskUsage[] | undefined): DiskUsage | null {
  return (disks ?? []).reduce<DiskUsage | null>((max, d) => (!max || (d.percent ?? 0) > (max.percent ?? 0) ? d : max), null);
}
