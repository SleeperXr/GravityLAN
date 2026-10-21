import { onBeforeUnmount, ref, watch, type Ref } from 'vue';
import { api, createMetricsSocket } from '@/api/client';
import { toMetricsData, unwrap, type MetricsData, type RawSample } from '@/lib/metrics';

/**
 * Metrics of an active agent: the last stored sample first, then live values from the
 * metrics socket. Null while there is no active agent or no sample yet.
 */
export function useLiveMetrics(deviceId: Ref<number>, enabled: Ref<boolean> = ref(true)) {
  const metrics = ref<MetricsData | null>(null);
  const active = ref(false);
  let socket: WebSocket | null = null;
  let generation = 0;

  function stop() {
    generation++;
    try {
      socket?.close();
    } catch {
      // already closed
    }
    socket = null;
  }

  async function start(id: number) {
    stop();
    const mine = generation;
    metrics.value = null;
    active.value = false;
    try {
      const status = await api.getAgentStatus(id);
      if (mine !== generation) return;
      active.value = status.is_active;
      if (!status.is_active) return;
      try {
        const history = await api.getAgentMetrics(id, 1);
        if (mine === generation && history.snapshots.length > 0) {
          metrics.value = toMetricsData(history.snapshots[history.snapshots.length - 1] as RawSample);
        }
      } catch {
        // no stored sample yet
      }
      if (mine !== generation) return;
      socket = createMetricsSocket(id, (msg) => {
        if (mine === generation) metrics.value = toMetricsData(unwrap(msg));
      });
    } catch {
      if (mine === generation) active.value = false;
    }
  }

  watch(
    [deviceId, enabled],
    ([id, on]) => {
      if (on) void start(id);
      else stop();
    },
    { immediate: true },
  );
  onBeforeUnmount(stop);

  return { metrics, active };
}
