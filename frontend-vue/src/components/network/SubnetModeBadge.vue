<script setup lang="ts">
import { computed } from 'vue';
import type { Subnet } from '@/types';
import Badge from '@/components/ui/Badge.vue';
import { t } from '@/i18n';

/** How GravityLAN reaches a subnet: L2 direct (ARP), L2 via an agent probe, or L3 routed. */
const props = withDefaults(defineProps<{ subnet: Subnet; long?: boolean }>(), { long: false });

const mode = computed(() => {
  const s = props.subnet;
  const probe = s.probe_device_name || s.probe_device_ip || 'Agent';
  if (s.is_agent_probe) return { tone: 'info' as const, short: t('network.l2_probe'), long: t('network.l2_probe_via', { probe }), desc: t('network.l2_probe_desc', { probe }) };
  if (s.is_direct_l2 !== false) {
    return {
      tone: 'accent' as const,
      short: 'L2',
      long: s.interface_name ? t('network.l2_direct_via', { interface: s.interface_name }) : t('network.l2_direct'),
      desc: t('network.l2_direct_desc'),
    };
  }
  return { tone: 'warn' as const, short: 'L3', long: t('network.l3_routed_no_arp'), desc: t('network.l3_routed_desc') };
});
</script>

<template>
  <Badge :tone="mode.tone" :title="mode.desc">{{ long ? mode.long : mode.short }}</Badge>
</template>
