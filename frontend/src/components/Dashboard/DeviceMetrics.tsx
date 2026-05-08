import { useState, useEffect, useRef } from 'react';
import { api, createMetricsSocket } from '../../api/client';
import { Cpu, MemoryStick, HardDrive, Thermometer, Activity } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface MetricsData {
  cpu_percent: number;
  ram: { used_mb: number; total_mb: number; percent: number };
  disk: { path: string; total_gb: number; used_gb: number; percent: number }[];
  temperature: number | null;
  network: Record<string, { rx_bytes_sec: number; tx_bytes_sec: number }>;
  timestamp: string;
}

interface DeviceMetricsProps {
  deviceId: number;
  compact?: boolean;
  onUpdate?: (metrics: MetricsData) => void;
}

/** Mini progress bar for inline metrics display. */
function MiniBar({ percent, color }: { percent: number; color: string }) {
  return (
    <div style={{
      width: '100%', height: 4, background: 'rgba(255,255,255,0.06)',
      borderRadius: 2, overflow: 'hidden'
    }}>
      <div style={{
        width: `${Math.min(percent, 100)}%`, height: '100%',
        background: color,
        borderRadius: 2,
        transition: 'width 0.5s ease'
      }} />
    </div>
  );
}

/** Determine color based on utilization percentage. */
function utilizationColor(percent: number): string {
  if (percent >= 90) return '#ef4444';
  if (percent >= 70) return '#f59e0b';
  return '#10b981';
}

/** Determine color based on temperature. */
function tempColor(temp: number): string {
  if (temp >= 80) return '#ef4444';
  if (temp >= 60) return '#f59e0b';
  return '#10b981';
}

/** Format bytes per second to human-readable string. */
function formatBps(bytesPerSec: number): string {
  if (bytesPerSec >= 1_000_000) return `${(bytesPerSec / 1_000_000).toFixed(1)} MB/s`;
  if (bytesPerSec >= 1_000) return `${(bytesPerSec / 1_000).toFixed(0)} KB/s`;
  return `${bytesPerSec} B/s`;
}

/**
 * Real-time device metrics overlay for DeviceCards.
 */
export function DeviceMetrics({ deviceId, compact = true, onUpdate }: DeviceMetricsProps) {
  const { t } = useTranslation();
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [isAgentActive, setIsAgentActive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let mounted = true;

    const checkAgent = async () => {
      try {
        const status = await api.getAgentStatus(deviceId);
        if (!mounted) return;
        setIsAgentActive(status.is_active);
        if (status.is_active) {
          try {
            const history = await api.getAgentMetrics(deviceId, 1);
            if (history.snapshots.length > 0 && mounted) {
              setMetrics(history.snapshots[history.snapshots.length - 1]);
            }
          } catch { /* metrics not available yet */ }

          try {
            wsRef.current = createMetricsSocket(deviceId, (msg) => {
              if (mounted) {
                // WebSocket messages are wrapped: { type: 'metrics', data: { ... } }
                const snapshot = (msg && msg.type === 'metrics' && msg.data) ? msg.data : msg;
                setMetrics(snapshot);
                if (onUpdate) onUpdate(snapshot);
              }
            });
          } catch { /* WebSocket unavailable */ }
        }
      } catch {
        if (mounted) setIsAgentActive(false);
      }
    };

    checkAgent();

    return () => {
      mounted = false;
      try { wsRef.current?.close(); } catch { /* ignore */ }
    };
  }, [deviceId]);

  if (!isAgentActive || !metrics) return null;

  if (compact) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', gap: 4,
        padding: '4px 0 0', borderTop: '1px solid var(--border-subtle)',
        marginTop: 'auto', width: '100%'
      }}>
        {/* CPU */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Cpu size={11} style={{ color: utilizationColor(metrics.cpu_percent ?? 0), flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <MiniBar percent={metrics.cpu_percent ?? 0} color={utilizationColor(metrics.cpu_percent ?? 0)} />
          </div>
          <span style={{ fontSize: '0.6rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', minWidth: 32, textAlign: 'right' }}>
            {(metrics.cpu_percent ?? 0).toFixed(0)}%
          </span>
        </div>

        {/* RAM */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <MemoryStick size={11} style={{ color: utilizationColor(metrics.ram?.percent ?? 0), flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <MiniBar percent={metrics.ram?.percent ?? 0} color={utilizationColor(metrics.ram?.percent ?? 0)} />
          </div>
          <span style={{ fontSize: '0.6rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', minWidth: 32, textAlign: 'right' }}>
            {(metrics.ram?.percent ?? 0).toFixed(0)}%
          </span>
        </div>

        {/* Disks */}
        {(metrics.disk || []).map((d, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <HardDrive size={11} style={{ color: utilizationColor(d.percent ?? 0), flexShrink: 0 }} title={d.path} />
            <div style={{ flex: 1 }}>
              <MiniBar percent={d.percent ?? 0} color={utilizationColor(d.percent ?? 0)} />
            </div>
            <span style={{ fontSize: '0.6rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', minWidth: 32, textAlign: 'right' }}>
              {(d.percent ?? 0).toFixed(0)}%
            </span>
          </div>
        ))}

        {/* Temperature */}
        {metrics.temperature != null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Thermometer size={11} style={{ color: tempColor(metrics.temperature), flexShrink: 0 }} />
            <span style={{ 
              fontSize: '0.6rem', fontFamily: 'var(--font-mono)', fontWeight: 700,
              color: tempColor(metrics.temperature)
            }}>
              {metrics.temperature.toFixed(0)}°C
            </span>
          </div>
        )}
      </div>
    );
  }

  // Expanded view
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 10,
      padding: '12px', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)',
      width: '100%'
    }}>
      {/* CPU */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            <Cpu size={13} /> {t('agent.cpu')}
          </span>
          <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 700, color: utilizationColor(metrics.cpu_percent ?? 0) }}>
            {(metrics.cpu_percent ?? 0).toFixed(1)}%
          </span>
        </div>
        <MiniBar percent={metrics.cpu_percent ?? 0} color={utilizationColor(metrics.cpu_percent ?? 0)} />
      </div>

      {/* RAM */}
      {metrics.ram && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <MemoryStick size={13} /> {t('agent.ram')}
            </span>
            <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
              {((metrics.ram.used_mb || 0) / 1024).toFixed(1)} / {((metrics.ram.total_mb || 0) / 1024).toFixed(1)} GB
            </span>
          </div>
          <MiniBar percent={metrics.ram.percent ?? 0} color={utilizationColor(metrics.ram.percent ?? 0)} />
        </div>
      )}

      {/* Disks */}
      {(metrics.disk || []).map((d) => (
        <div key={d.path}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <HardDrive size={13} /> {d.path}
            </span>
            <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
              {d.used_gb ?? 0} / {d.total_gb ?? 0} GB
            </span>
          </div>
          <MiniBar percent={d.percent ?? 0} color={utilizationColor(d.percent ?? 0)} />
        </div>
      ))}

      {/* Temperature */}
      {metrics.temperature != null && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            <Thermometer size={13} /> {t('agent.temperature')}
          </span>
          <span style={{
            fontSize: '0.85rem', fontWeight: 700, fontFamily: 'var(--font-mono)',
            color: tempColor(metrics.temperature),
            padding: '2px 8px', borderRadius: 6,
            background: `${tempColor(metrics.temperature)}15`
          }}>
            {metrics.temperature.toFixed(1)}°C
          </span>
        </div>
      )}

      {/* Network */}
      {metrics.network && Object.keys(metrics.network).length > 0 && (
        <div>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: 4 }}>
            <Activity size={13} /> {t('agent.network')}
          </span>
          {Object.entries(metrics.network).map(([iface, data]) => (
            <div key={iface} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)' }}>
              <span>{iface}</span>
              <span>↓{formatBps(data?.rx_bytes_sec ?? 0)} ↑{formatBps(data?.tx_bytes_sec ?? 0)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
