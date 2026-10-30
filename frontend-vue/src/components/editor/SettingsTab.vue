<script setup lang="ts">
import { computed } from 'vue';
import { Bell, BellOff, Orbit, Radio, RefreshCw, Server, Wifi } from 'lucide-vue-next';
import type { Device, DeviceGroup, Rack } from '@/types';
import type { DeviceFormData } from '@/lib/deviceForm';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import Switch from '@/components/ui/Switch.vue';
import Textarea from '@/components/ui/Textarea.vue';
import { deviceLabel } from '@/lib/networks';
import { isOnOrbit } from '@/components/orbit/orbitModel';
import { useAppearance } from '@/stores/appearance';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/** "General" tab: identity, placement, role and monitoring of a device. */
const form = defineModel<DeviceFormData>('form', { required: true });
const props = defineProps<{ device: Device; devices: Device[]; groups: DeviceGroup[]; racks: Rack[]; refreshing: boolean }>();
const emit = defineEmits<{ refreshInfo: []; submit: [] }>();

/** Orbit map visibility is an appearance setting, saved right away rather than with the form */
const appearance = useAppearance();
const { showToast } = useToast();
void appearance.load();
const onOrbit = computed({
  get: () => isOnOrbit(props.device, appearance.orbitVisibility),
  set: (shown: boolean) => {
    appearance.setOrbitVisible(props.device.id, shown).catch((err: Error) => showToast('error', t('notifications.save_failed'), err.message));
  },
});

const groupOptions = computed(() => [
  { value: null, label: t('dashboard.unassigned_devices') },
  ...props.groups.map((g) => ({ value: g.id, label: g.name })),
]);
const hostOptions = computed(() => [
  { value: null, label: t('editor.no_parent') },
  ...props.devices.filter((d) => d.id !== props.device.id && d.is_host).map((d) => ({ value: d.id, label: deviceLabel(d) })),
]);
const rackOptions = computed(() => [{ value: null, label: t('editor.no_rack') }, ...props.racks.map((r) => ({ value: r.id, label: r.name }))]);

const roles = [
  { key: 'is_wlan', icon: Wifi, label: 'editor.wlan_client', desc: 'editor.wlan_client_desc' },
  { key: 'is_ap', icon: Radio, label: 'editor.access_point', desc: 'editor.access_point_desc' },
  { key: 'is_host', icon: Server, label: 'editor.physical_host', desc: 'editor.physical_host_desc' },
] as const;

const badges = computed(() => [
  { id: null, label: t('editor.none') },
  { id: 'vm', label: 'VM' },
  { id: 'docker', label: 'Docker' },
] as const);

function intOrNull(value: string | number | null | undefined): number | null {
  if (value === '' || value === null || value === undefined) return null;
  const n = typeof value === 'number' ? value : parseInt(value, 10);
  return Number.isNaN(n) ? null : n;
}
</script>

<template>
  <form class="space-y-6" @submit.prevent="emit('submit')">
    <section class="space-y-4">
      <Field v-slot="{ id }" :label="t('editor.display_name')">
        <div class="flex gap-2">
          <Input :id="id" v-model="form.display_name" :placeholder="device.hostname || device.ip" />
          <Button :loading="refreshing" :title="t('editor.refresh_hint')" @click="emit('refreshInfo')">
            <RefreshCw v-if="!refreshing" aria-hidden="true" />
            <span class="hidden sm:inline">{{ t('editor.refresh_info') }}</span>
          </Button>
        </div>
      </Field>
      <div class="grid gap-4 sm:grid-cols-2">
        <Field v-slot="{ id }" :label="t('editor.group')">
          <Select :id="id" v-model="form.group_id" :options="groupOptions" />
        </Field>
        <Field v-slot="{ id }" :label="t('editor.vendor')">
          <Input :id="id" v-model="form.vendor" :placeholder="t('common.unknown')" />
        </Field>
      </div>
      <Field v-slot="{ id }" :label="t('editor.parent_device')">
        <Select :id="id" v-model="form.parent_id" :options="hostOptions" />
      </Field>
    </section>

    <section class="space-y-4 border-t border-line pt-5">
      <div class="grid gap-4 sm:grid-cols-[2fr_1fr_1fr]">
        <Field v-slot="{ id }" :label="t('editor.rack_position')">
          <Select :id="id" v-model="form.rack_id" :options="rackOptions" />
        </Field>
        <Field v-slot="{ id }" :label="t('gv.editor.rack_unit')" :hint="t('gv.editor.rack_unit_hint')">
          <Input :id="id" :model-value="form.rack_unit" type="number" min="1" inputmode="numeric" mono @update:model-value="(v) => (form.rack_unit = intOrNull(v))" />
        </Field>
        <Field v-slot="{ id }" :label="t('editor.rack_height')" :hint="t('gv.editor.rack_height_hint')">
          <Input :id="id" :model-value="form.rack_height" type="number" min="1" max="10" mono @update:model-value="(v) => (form.rack_height = intOrNull(v) ?? 1)" />
        </Field>
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <Field v-slot="{ id }" :label="t('gv.editor.tile_size')" :hint="t('gv.editor.tile_size_hint')">
          <div class="flex items-center gap-2">
            <Input :id="id" :model-value="form.w" type="number" min="1" max="12" mono :aria-label="`${t('editor.grid_size')} W`" @update:model-value="(v) => (form.w = intOrNull(v) ?? 1)" />
            <span class="text-fg-subtle" aria-hidden="true">×</span>
            <Input :model-value="form.h" type="number" min="1" max="10" mono :aria-label="`${t('editor.grid_size')} H`" @update:model-value="(v) => (form.h = intOrNull(v) ?? 1)" />
          </div>
        </Field>
        <fieldset class="flex min-w-0 flex-col gap-1.5">
          <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('editor.badge') }}</legend>
          <div class="flex rounded-md border border-line bg-sunken p-0.5">
            <button
              v-for="badge in badges"
              :key="String(badge.id)"
              type="button"
              class="h-8 flex-1 rounded-[5px] text-xs font-semibold transition-colors"
              :class="form.virtual_type === badge.id ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
              :aria-pressed="form.virtual_type === badge.id"
              @click="form.virtual_type = badge.id"
            >
              {{ badge.label }}
            </button>
          </div>
        </fieldset>
      </div>
    </section>

    <section class="grid gap-2 border-t border-line pt-5 sm:grid-cols-3">
      <button
        v-for="role in roles"
        :key="role.key"
        type="button"
        role="switch"
        :aria-checked="form[role.key]"
        class="flex items-center gap-3 rounded-md border p-3 text-left transition-colors"
        :class="form[role.key] ? 'border-info/50 bg-info/[0.07]' : 'border-line bg-raised hover:border-line-strong'"
        @click="form[role.key] = !form[role.key]"
      >
        <span class="flex size-8 shrink-0 items-center justify-center rounded-md" :class="form[role.key] ? 'bg-info text-canvas' : 'bg-sunken text-fg-subtle'">
          <component :is="role.icon" class="size-4" aria-hidden="true" />
        </span>
        <span class="min-w-0">
          <span class="block text-sm font-medium text-fg">{{ t(role.label) }}</span>
          <span class="block text-xs text-fg-subtle">{{ t(role.desc) }}</span>
        </span>
      </button>
    </section>

    <label class="flex cursor-pointer items-center gap-3 rounded-md border p-3 transition-colors" :class="form.alert_offline ? 'border-accent/40 bg-accent/[0.06]' : 'border-line bg-raised'">
      <span class="flex size-8 shrink-0 items-center justify-center rounded-md" :class="form.alert_offline ? 'bg-accent text-accent-fg' : 'bg-sunken text-fg-subtle'">
        <Bell v-if="form.alert_offline" class="size-4" aria-hidden="true" />
        <BellOff v-else class="size-4" aria-hidden="true" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block text-sm font-medium text-fg">{{ form.alert_offline ? t('health_page.alert_offline_24_7') : t('health_page.alert_offline_client') }}</span>
        <span id="alert-offline-hint" class="block text-xs text-fg-subtle">{{ t('health_page.alert_offline_hint') }}</span>
      </span>
      <Switch v-model="form.alert_offline" :aria-label="t('health_page.alert_offline_24_7')" aria-describedby="alert-offline-hint" />
    </label>

    <label class="flex cursor-pointer items-center gap-3 rounded-md border p-3 transition-colors" :class="onOrbit ? 'border-accent/40 bg-accent/[0.06]' : 'border-line bg-raised'">
      <span class="flex size-8 shrink-0 items-center justify-center rounded-md" :class="onOrbit ? 'bg-accent text-accent-fg' : 'bg-sunken text-fg-subtle'">
        <Orbit class="size-4" aria-hidden="true" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block text-sm font-medium text-fg">{{ t('gv.orbit.show_on_orbit') }}</span>
        <span id="on-orbit-hint" class="block text-xs text-fg-subtle">{{ t('gv.orbit.show_on_orbit_hint') }}</span>
      </span>
      <Switch v-model="onOrbit" :aria-label="t('gv.orbit.show_on_orbit')" aria-describedby="on-orbit-hint" />
    </label>

    <Field v-slot="{ id }" :label="t('editor.notes')">
      <Textarea :id="id" v-model="form.notes" :placeholder="t('editor.notes_placeholder')" rows="3" />
    </Field>

    <dl class="grid gap-4 rounded-md border border-line bg-raised p-4 text-sm sm:grid-cols-2">
      <div>
        <dt class="gl-eyebrow mb-1.5">{{ t('editor.system_info') }}</dt>
        <dd class="grid grid-cols-[3.5rem_1fr] gap-y-1">
          <span class="text-fg-subtle">IP</span><span class="font-mono text-fg">{{ device.ip }}</span>
          <span class="text-fg-subtle">MAC</span><span class="font-mono text-fg">{{ device.mac || 'N/A' }}</span>
        </dd>
      </div>
      <div>
        <dt class="gl-eyebrow mb-1.5">{{ t('editor.network_info') }}</dt>
        <dd class="text-fg-muted">
          {{ device.hostname || t('editor.no_dns_name') }}
          <span v-if="device.hostname?.includes('.')" class="mt-0.5 block font-mono text-xs text-info-text">FQDN: {{ device.hostname }}</span>
        </dd>
      </div>
    </dl>
  </form>
</template>
