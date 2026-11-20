<script setup lang="ts">
/**
 * Shown wherever a device's online state appears while it has an open MAC conflict: another MAC answers at
 * its address, so the device is not probed and its state is the last known one until the conflict is
 * adopted or dismissed (app.services.mac_observations, presence_frozen in the API).
 */
import { CircleHelp } from 'lucide-vue-next';
import Badge from '@/components/ui/Badge.vue';
import { t } from '@/i18n';
</script>

<template>
  <Badge tone="warn" :title="t('gv.mac_conflicts.presence_frozen_title')" data-testid="presence-frozen">
    <CircleHelp aria-hidden="true" />{{ t('gv.mac_conflicts.presence_frozen') }}
  </Badge>
</template>
