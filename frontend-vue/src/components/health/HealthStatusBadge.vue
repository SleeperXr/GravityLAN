<script setup lang="ts">
import { computed } from 'vue';
import Badge from '@/components/ui/Badge.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { statusMeta, type HealthStatus } from './healthModel';

const props = defineProps<{ status: HealthStatus }>();
const meta = computed(() => statusMeta(props.status));
</script>

<template>
  <Badge :tone="meta.tone" class="gap-1.5 rounded-full px-2">
    <StatusDot size="sm" :state="meta.dot" :pulse="status === 'flapping'" />{{ meta.label }}
  </Badge>
</template>
