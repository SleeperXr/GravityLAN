<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue';
import Select from '@/components/ui/Select.vue';
import { formatDateTime, t } from '@/i18n';
import { activeTimeZone, browserTimeZone, setTimeZone, timeZoneNames, timeZonePreference, utcOffsetLabel } from '@/i18n/timeZone';

/**
 * The time zone every time in GravityUI is shown in: logs, charts, audit, agents. The server sends
 * UTC, so this works the same whatever zone the server or its container runs in. Kept per browser.
 */
const zone = computed<string>({ get: () => timeZonePreference.value, set: (next) => setTimeZone(next) });

// The offset of each zone is read once; it only shifts at a summer-time change, which a reload picks up
const browser = browserTimeZone();
const zoneOptions = timeZoneNames().map((name) => ({ value: name, label: `${name.replaceAll('_', ' ')} (${utcOffsetLabel(name)})` }));
const options = computed(() => [
  { value: '', label: t('gv.settings.timezone_browser', { zone: `${browser} (${utcOffsetLabel(browser)})` }) },
  ...zoneOptions,
]);

// The current time in the chosen zone, so the choice can be checked at a glance
const now = ref(new Date());
const timer = window.setInterval(() => (now.value = new Date()), 1000);
onBeforeUnmount(() => window.clearInterval(timer));
const preview = computed(() => formatDateTime(now.value, { dateStyle: 'medium', timeStyle: 'medium' }));
</script>

<template>
  <fieldset class="min-w-0 flex-1 basis-64">
    <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('gv.settings.timezone') }}</legend>
    <Select v-model="zone" :options="options" :aria-label="t('gv.settings.timezone')" aria-describedby="timezone-hint" />
    <p id="timezone-hint" class="mt-1.5 text-xs text-fg-subtle">
      {{ t('gv.settings.timezone_hint', { time: preview, zone: activeTimeZone() }) }}
    </p>
  </fieldset>
</template>
