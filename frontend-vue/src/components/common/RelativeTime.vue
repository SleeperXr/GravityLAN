<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import { formatDateTime, locale } from '@/i18n';

/** "vor 5 Minuten" with the exact local time in the tooltip; refreshes every 30 s. */
const props = defineProps<{ date: string | number | Date | null | undefined }>();

const now = ref(Date.now());
const timer = window.setInterval(() => (now.value = Date.now()), 30000);
onBeforeUnmount(() => window.clearInterval(timer));

const parsed = computed(() => {
  if (!props.date) return null;
  const d = props.date instanceof Date ? props.date : new Date(props.date);
  return Number.isNaN(d.getTime()) ? null : d;
});

const text = computed(() => {
  if (!parsed.value) return '—';
  const diff = (parsed.value.getTime() - now.value) / 1000;
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat(locale.value === 'de' ? 'de-DE' : 'en-US', { numeric: 'auto' });
  if (abs < 45) return rtf.format(0, 'second');
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day');
  return formatDateTime(parsed.value, { dateStyle: 'medium' });
});
</script>

<template>
  <time v-if="parsed" :datetime="parsed.toISOString()" :title="formatDateTime(parsed)">{{ text }}</time>
  <span v-else>—</span>
</template>
