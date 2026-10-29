<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import { formatDateTime } from '@/i18n';
import { parseDate, relativeTimeText } from '@/lib/relativeTime';

/** "vor 5 Minuten" with the exact local time in the tooltip; refreshes every 30 s. */
const props = defineProps<{ date: string | number | Date | null | undefined }>();

const now = ref(Date.now());
const timer = window.setInterval(() => (now.value = Date.now()), 30000);
onBeforeUnmount(() => window.clearInterval(timer));

const parsed = computed(() => parseDate(props.date));
const text = computed(() => (parsed.value ? relativeTimeText(parsed.value, now.value) : '—'));
</script>

<template>
  <time v-if="parsed" :datetime="parsed.toISOString()" :title="formatDateTime(parsed)">{{ text }}</time>
  <span v-else>—</span>
</template>
