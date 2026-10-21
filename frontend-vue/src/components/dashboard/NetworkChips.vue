<script setup lang="ts">
import { computed } from 'vue';
import type { Device } from '@/types';
import { chipName, deviceLabel, deviceNetworks } from '@/lib/networks';
import { t } from '@/i18n';

/** One chip per network a multi-homed device (e.g. a VLAN router) answers in. */
const props = defineProps<{ device: Device }>();
const chips = computed(() => deviceNetworks(props.device));
</script>

<template>
  <ul v-if="chips.length > 1" class="flex flex-wrap gap-1" :aria-label="t('interfaces.networks_of', { name: deviceLabel(device) })">
    <li
      v-for="chip in chips"
      :key="chip.ip"
      class="inline-flex h-5 items-center gap-1 rounded-sm border border-line bg-raised pr-1.5 pl-1 text-[11px] text-fg-muted"
      :class="!chip.isOnline && 'opacity-60'"
      :title="`${chip.ip}${chip.vlanId != null ? ` · VLAN ${chip.vlanId}` : ''}${chip.isPrimary ? ` · ${t('interfaces.primary')}` : ''} · ${chip.isOnline ? t('network.online') : t('network.offline')}`"
    >
      <span class="size-2 rounded-[3px]" :style="{ backgroundColor: chip.color }" aria-hidden="true" />
      <span class="max-w-24 truncate">{{ chipName(chip) }}</span>
      <span v-if="chip.vlanId != null" class="font-mono text-[10px] text-fg-subtle">{{ chip.vlanId }}</span>
      <span class="sr-only">{{ chip.ip }}, {{ chip.isOnline ? t('network.online') : t('network.offline') }}</span>
    </li>
  </ul>
</template>
