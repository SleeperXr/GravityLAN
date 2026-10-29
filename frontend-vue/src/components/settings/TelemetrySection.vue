<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { Check, Trash2 } from 'lucide-vue-next';
import { api, type TelemetryPurge, type TelemetryRetention, type TelemetryStatus } from '@/api/client';
import type { Device } from '@/types';
import SettingsSection from './SettingsSection.vue';
import ActionRow from './ActionRow.vue';
import UnitField from './UnitField.vue';
import Button from '@/components/ui/Button.vue';
import Select from '@/components/ui/Select.vue';
import { useToast } from '@/composables/useToast';
import { useArmed } from '@/composables/useArmed';
import { formatDateTime, formatNumber, t } from '@/i18n';

/** Settings > Measurement data: size of both databases, retention per tier, cleanup. */
type PurgeKind = TelemetryPurge['scope'];
const { showToast } = useToast();
const { armed, confirmOrArm } = useArmed<PurgeKind>();

const status = ref<TelemetryStatus | null>(null);
const devices = ref<Device[]>([]);
const form = ref<Record<keyof TelemetryRetention, string>>({ raw_hours: '', hourly_days: '', daily_days: '' });
const olderThan = ref('30');
const deviceId = ref<number | null>(null);
const saving = ref(false);
const busy = ref<PurgeKind | null>(null);

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exp = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** exp;
  return `${formatNumber(value, { maximumFractionDigits: value >= 10 || exp === 0 ? 0 : 1 })} ${units[exp]}`;
}

/** The server sends naive UTC timestamps */
function utcDate(value: string | null): string {
  if (!value) return '–';
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date, { dateStyle: 'medium' });
}

const deviceLabel = (d: Device) => {
  const name = d.display_name || d.hostname;
  return name && name !== d.ip ? `${name} (${d.ip})` : d.ip;
};

function applyStatus(next: TelemetryStatus) {
  status.value = next;
  form.value = { raw_hours: String(next.retention.raw_hours), hourly_days: String(next.retention.hourly_days), daily_days: String(next.retention.daily_days) };
}

onMounted(() => {
  api.getTelemetryStatus().then(applyStatus).catch(() => {});
  api
    .getDevices()
    .then((list) => (devices.value = [...list].sort((a, b) => deviceLabel(a).localeCompare(deviceLabel(b)))))
    .catch(() => (devices.value = []));
});

const TIERS = [
  { key: 'raw', tables: ['device_health_samples', 'device_metrics'] },
  { key: 'rollups', tables: ['device_health_rollups', 'device_metrics_rollups'] },
] as const;

const tiers = computed(() => {
  const s = status.value;
  if (!s) return [];
  return TIERS.map((tier) => {
    const stats = tier.tables.map((name) => s.tables[name]);
    return {
      key: tier.key,
      rows: stats.reduce((sum, x) => sum + x.rows, 0),
      oldest: stats.map((x) => x.oldest).filter((v): v is string => !!v).sort()[0] ?? null,
    };
  });
});

/** Share of the telemetry database in all stored data, for the size bar. */
const telemetryShare = computed(() => {
  const s = status.value?.sizes;
  if (!s) return 0;
  const total = s.telemetry_bytes + s.inventory_bytes;
  return total ? (s.telemetry_bytes / total) * 100 : 0;
});

const isDirty = computed(() => !!status.value && (Object.keys(form.value) as (keyof TelemetryRetention)[]).some((k) => form.value[k] !== String(status.value!.retention[k])));
const rangeHint = (key: keyof TelemetryRetention, text: string) => {
  const limits = status.value?.limits;
  return limits ? `${text} ${t('telemetry_settings.range', { min: limits[key].min, max: limits[key].max })}` : text;
};

async function saveRetention() {
  saving.value = true;
  try {
    applyStatus(await api.updateTelemetryRetention({ raw_hours: Number(form.value.raw_hours), hourly_days: Number(form.value.hourly_days), daily_days: Number(form.value.daily_days) }));
    showToast('success', t('telemetry_settings.saved_title'), t('telemetry_settings.saved_body'));
  } catch (err) {
    showToast('error', t('common.error'), `${t('telemetry_settings.save_failed')} ${(err as Error).message}`);
  } finally {
    saving.value = false;
  }
}

const olderThanRequest = computed<TelemetryPurge | null>(() => {
  const days = Number(olderThan.value);
  return Number.isInteger(days) && days >= 1 ? { scope: 'older_than', older_than_days: days } : null;
});
const deviceRequest = computed<TelemetryPurge | null>(() => (deviceId.value ? { scope: 'device', device_id: deviceId.value } : null));

async function purge(request: TelemetryPurge | null) {
  if (!request || !confirmOrArm(request.scope)) return;
  busy.value = request.scope;
  const before = status.value?.sizes.telemetry_bytes ?? 0;
  try {
    const res = await api.purgeTelemetry(request);
    applyStatus(res);
    const rows = Object.values(res.deleted).reduce((sum, n) => sum + n, 0);
    showToast('success', t('telemetry_settings.purged_title'), t('telemetry_settings.purged_body', { rows: formatNumber(rows), freed: formatBytes(Math.max(0, before - res.sizes.telemetry_bytes)) }));
  } catch (err) {
    showToast('error', t('common.error'), `${t('telemetry_settings.purge_failed')} ${(err as Error).message}`);
  } finally {
    busy.value = null;
  }
}
</script>

<template>
  <SettingsSection id="telemetry" :title="t('telemetry_settings.title')" :description="t('telemetry_settings.description')">
    <div class="space-y-3">
      <!-- Two figures split by a rule; boxes inside the section card read as cards in cards -->
      <div class="grid grid-cols-2 divide-x divide-line">
        <div class="pr-4">
          <p class="gl-eyebrow">{{ t('telemetry_settings.size_telemetry') }}</p>
          <p class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ status ? formatBytes(status.sizes.telemetry_bytes) : '…' }}</p>
        </div>
        <div class="pl-4">
          <p class="gl-eyebrow">{{ t('telemetry_settings.size_inventory') }}</p>
          <p class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ status ? formatBytes(status.sizes.inventory_bytes) : '…' }}</p>
        </div>
      </div>
      <div v-if="status" class="flex h-1.5 overflow-hidden rounded-full bg-sunken" role="img" :aria-label="`${t('telemetry_settings.size_telemetry')}: ${Math.round(telemetryShare)} %`">
        <div class="bg-info" :style="{ width: `${telemetryShare}%` }" />
        <div class="flex-1 bg-fg-subtle/40" />
      </div>
    </div>

    <ul v-if="status" class="divide-y divide-line border-y border-line" :aria-label="t('telemetry_settings.tiers_label')">
      <li v-for="tier in tiers" :key="tier.key" class="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-fg">{{ t(`telemetry_settings.tier_${tier.key}`) }}</p>
          <p class="text-xs text-fg-subtle">{{ t(`telemetry_settings.tier_${tier.key}_desc`) }}</p>
        </div>
        <p class="font-mono text-xs text-fg-muted tabular">
          {{ t('telemetry_settings.rows', { rows: formatNumber(tier.rows) }) }}<span v-if="tier.oldest"> · {{ t('telemetry_settings.since', { date: utcDate(tier.oldest) }) }}</span>
        </p>
      </li>
    </ul>

    <div class="grid gap-4 md:grid-cols-3">
      <UnitField v-model="form.raw_hours" :label="t('telemetry_settings.raw_label')" :hint="rangeHint('raw_hours', t('telemetry_settings.raw_hint'))" :unit="t('telemetry_settings.unit_hours')" />
      <UnitField v-model="form.hourly_days" :label="t('telemetry_settings.hourly_label')" :hint="rangeHint('hourly_days', t('telemetry_settings.hourly_hint'))" :unit="t('settings.unit_days')" />
      <UnitField v-model="form.daily_days" :label="t('telemetry_settings.daily_label')" :hint="rangeHint('daily_days', t('telemetry_settings.daily_hint'))" :unit="t('settings.unit_days')" />
    </div>
    <div v-if="isDirty" class="flex justify-end gap-2">
      <Button size="sm" variant="ghost" :disabled="saving" @click="status && applyStatus(status)">{{ t('settings.discard') }}</Button>
      <Button size="sm" variant="primary" :loading="saving" @click="saveRetention"><Check v-if="!saving" aria-hidden="true" />{{ t('telemetry_settings.save_retention') }}</Button>
    </div>

    <ActionRow :title="t('telemetry_settings.purge_older_title')" :description="t('telemetry_settings.purge_older_desc')">
      <div class="w-28"><UnitField v-model="olderThan" :label="t('telemetry_settings.purge_older_input')" :unit="t('settings.unit_days')" :min="1" /></div>
      <Button size="sm" :variant="armed === 'older_than' ? 'danger' : 'danger-ghost'" :loading="busy === 'older_than'" :disabled="!olderThanRequest || busy !== null" @click="purge(olderThanRequest)">
        <Trash2 v-if="busy !== 'older_than'" aria-hidden="true" />{{ armed === 'older_than' ? t('telemetry_settings.really') : t('telemetry_settings.purge_older_button') }}
      </Button>
    </ActionRow>

    <ActionRow :title="t('telemetry_settings.purge_device_title')" :description="t('telemetry_settings.purge_device_desc')">
      <Select v-model="deviceId" class="w-56" :aria-label="t('telemetry_settings.purge_device_select')" :options="[{ value: null, label: t('telemetry_settings.purge_device_placeholder') }, ...devices.map((d) => ({ value: d.id, label: deviceLabel(d) }))]" />
      <Button size="sm" :variant="armed === 'device' ? 'danger' : 'danger-ghost'" :loading="busy === 'device'" :disabled="!deviceRequest || busy !== null" @click="purge(deviceRequest)">
        <Trash2 v-if="busy !== 'device'" aria-hidden="true" />{{ armed === 'device' ? t('telemetry_settings.really') : t('telemetry_settings.purge_device_button') }}
      </Button>
    </ActionRow>

    <ActionRow :title="t('telemetry_settings.purge_all_title')" :description="t('telemetry_settings.purge_all_desc')">
      <Button size="sm" :variant="armed === 'all' ? 'danger' : 'danger-ghost'" :loading="busy === 'all'" :disabled="busy !== null" @click="purge({ scope: 'all' })">
        <Trash2 v-if="busy !== 'all'" aria-hidden="true" />{{ armed === 'all' ? t('telemetry_settings.really') : t('telemetry_settings.purge_all_button') }}
      </Button>
    </ActionRow>
  </SettingsSection>
</template>
