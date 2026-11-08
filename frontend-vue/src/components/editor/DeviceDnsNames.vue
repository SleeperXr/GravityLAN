<script setup lang="ts">
import { computed } from 'vue';
import type { Device, HostnameSource } from '@/types';
import Select from '@/components/ui/Select.vue';
import { t } from '@/i18n';

/** What each DNS server calls the device, and which of them names it. Nothing before the first two-server lookup. */
const props = defineProps<{ device: Device; saving?: boolean }>();
const emit = defineEmits<{ hostnameSource: [source: HostnameSource] }>();

/** Why a DNS server gave no name, short and as a hint; answers kept before reasons existed say "no answer" */
const REASONS = ['no_entry', 'timeout', 'refused', 'server_error', 'error'];
const reasonOf = (n: '1' | '2') => {
  const reason = props.device.dns_errors?.[n];
  return reason && REASONS.includes(reason) ? reason : null;
};
const noNameLabel = (n: '1' | '2') => {
  const reason = reasonOf(n);
  return reason ? t(`gv.dns.reason_${reason}`) : t('gv.dns.no_answer');
};
const noNameHint = (n: '1' | '2') => {
  const reason = reasonOf(n);
  return reason ? t(`gv.dns.reason_${reason}_hint`) : undefined;
};

/** Which DNS server names the device; a server without an answer cannot be picked */
const sourceOptions = computed(() => [
  { value: 'auto' as HostnameSource, label: t('gv.dns.source_auto') },
  ...(['1', '2'] as const).map((n) => ({
    value: `dns${n}` as HostnameSource,
    label: t('gv.dns.source_dns', { n }),
    disabled: !props.device.dns_names?.[n] && props.device.hostname_source !== `dns${n}`,
  })),
]);
</script>

<template>
  <div v-if="device.dns_names" class="sm:col-span-2" data-test="dns-names">
    <dt class="gl-eyebrow mb-1.5">{{ t('gv.dns.names_title') }}</dt>
    <dd class="flex flex-wrap items-center gap-x-6 gap-y-2">
      <span v-for="n in (['1', '2'] as const)" :key="n" class="grid grid-cols-[3.5rem_1fr] items-baseline">
        <span class="text-fg-subtle">DNS {{ n }}</span>
        <span v-if="device.dns_names[n]" class="font-mono text-fg">{{ device.dns_names[n] }}</span>
        <span v-else class="text-fg-subtle" :title="noNameHint(n)" :data-test="`dns-reason-${n}`">{{ noNameLabel(n) }}</span>
      </span>
      <Select
        class="ml-auto w-56"
        :model-value="device.hostname_source ?? 'auto'"
        :options="sourceOptions"
        :disabled="saving"
        :aria-label="t('gv.dns.source_label')"
        data-test="hostname-source"
        @update:model-value="(v) => emit('hostnameSource', v as HostnameSource)"
      />
    </dd>
  </div>
</template>
