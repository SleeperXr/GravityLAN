import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { DiscoveredHost } from '@/types';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/** Hosts the scanner found that are not (yet) in the overview (port of React NetworkContext). */
export const useDiscoveryStore = defineStore('discovery', () => {
  const hosts = ref<DiscoveredHost[]>([]);
  const isDiscovering = ref(false);
  const { showToast } = useToast();

  async function load() {
    try {
      hosts.value = await api.getDiscoveredHosts();
    } catch {
      // keep the last list
    }
  }

  async function runDiscovery(prefix: string) {
    isDiscovering.value = true;
    showToast('info', t('common.loading'), `${t('network.scan_subnet')} ${prefix}.0/24...`);
    try {
      const res = await api.liveDiscovery({ subnets: [`${prefix}.0/24`] });
      // Reload all hosts so other subnets stay in the list
      await load();
      showToast('success', t('notifications.scan_completed'), t('notifications.devices_discovered', { count: Array.isArray(res) ? res.length : 0 }));
    } catch (err) {
      showToast('error', t('notifications.scan_failed'), (err as Error).message || t('notifications.scan_failed_text'));
    } finally {
      isDiscovering.value = false;
    }
  }

  async function update(id: number, data: { custom_name?: string; is_monitored?: boolean; is_reserved?: boolean }) {
    try {
      const updated = await api.patchDiscoveredHost(id, data);
      hosts.value = hosts.value.map((h) => (h.id === id ? updated : h));
      showToast('success', t('notifications.saved'), t('notifications.changes_applied'));
    } catch {
      showToast('error', t('common.error'), t('notifications.device_update_failed'));
    }
  }

  async function remove(id: number, ip: string) {
    try {
      await api.deleteDiscoveredHost(id);
      hosts.value = hosts.value.filter((h) => h.id !== id);
      showToast('success', t('common.success'), t('notifications.host_removed', { ip }));
    } catch {
      showToast('error', t('common.error'), t('notifications.delete_failed'));
    }
  }

  function patchLocal(ip: string, patch: Partial<DiscoveredHost>) {
    hosts.value = hosts.value.map((h) => (h.ip === ip ? { ...h, ...patch } : h));
  }

  function dropLocal(ip: string) {
    hosts.value = hosts.value.filter((h) => h.ip !== ip);
  }

  return { hosts, isDiscovering, load, runDiscovery, update, remove, patchLocal, dropLocal };
});
