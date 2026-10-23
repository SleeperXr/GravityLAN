<script setup lang="ts">
import { computed, ref } from 'vue';
import { Activity, Eye, EyeOff, Info, Lock, LockOpen, Plus, Save, Trash2 } from 'lucide-vue-next';
import { PopoverArrow, PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui';
import type { Device } from '@/types';
import type { Tile } from '@shared/components/Network/subnet/model';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';

/**
 * One address of the /24 map. Known addresses open a popover with details and actions on
 * click or Enter (works on touch and keyboard, unlike the hover tooltip of the React UI).
 */
const props = defineProps<{ tile: Tile; scanBusy: boolean; addBusy: boolean; showAreaLabel: boolean; lineColor?: string }>();
const emit = defineEmits<{
  openDevice: [device: Device];
  updateDevice: [id: number, data: Partial<Device>];
  updateHost: [id: number, data: { custom_name?: string; is_monitored?: boolean; is_reserved?: boolean }];
  scanDevice: [id: number, ip: string];
  scanHost: [ip: string];
  addDevice: [ip: string];
  deleteHost: [id: number, ip: string];
}>();

const open = ref(false);
const customName = ref(props.tile.discovered?.custom_name ?? '');
const device = computed(() => props.tile.device);
const host = computed(() => props.tile.discovered);
const known = computed(() => !!(device.value || host.value));
const online = computed(() => props.tile.status === 'online');
const name = computed(() => device.value?.display_name || host.value?.custom_name || host.value?.hostname || t('network.unknown_device'));

/** online/offline overview device, discovered-only host, reserved or free address */
const kind = computed(() => {
  if (device.value) return online.value ? 'device-online' : 'device-offline';
  if (host.value) return online.value ? 'host-online' : 'host-offline';
  return props.tile.status === 'reserved' ? 'reserved' : 'free';
});

const tileClass = computed(
  () =>
    ({
      'device-online': 'text-fg font-semibold',
      'device-offline': 'border-danger/45 bg-danger/[0.07] text-fg-muted',
      'host-online': 'border-info/45 bg-info/[0.1] text-fg',
      'host-offline': 'border-line-strong bg-raised text-fg-subtle',
      reserved: 'border-dashed border-line-strong text-fg-subtle',
      free: 'border-line text-fg-subtle',
    })[kind.value],
);

// Overview devices that are up wear their line's colour (a station on that line)
const lineStyle = computed(() => {
  if (kind.value !== 'device-online') return undefined;
  const color = props.lineColor ?? 'var(--gl-accent)';
  return { borderColor: `color-mix(in oklab, ${color} 55%, transparent)`, backgroundColor: `color-mix(in oklab, ${color} 14%, transparent)` };
});

const label = computed(() => {
  const state = known.value ? (online.value ? t('network.online') : t('network.offline')) : t('gv.network.free');
  return `${props.tile.ip}, ${known.value ? `${name.value}, ` : ''}${state}`;
});

/**
 * Device icons are stored either as an emoji or as an icon name of the classic UI ("server").
 * Only an emoji can be drawn as text; a name would print the word into the tile.
 */
const emojiIcon = computed(() => {
  const icon = device.value?.icon;
  return icon && /\p{Extended_Pictographic}/u.test(icon) ? icon : null;
});

/** "22 SSH" for a named service, plain "8080" when the name only repeats the port. */
function serviceText(s: { name?: string | null; port: number }): string {
  const name = s.name?.replace('Service ', '').trim();
  return name && name !== String(s.port) ? `${s.port} ${name}` : String(s.port);
}

const ports = computed(() => [
  ...(device.value?.services ?? []).filter((s) => s.is_up).map((s) => ({ key: `s${s.id}`, text: serviceText(s), tone: 'info' })),
  ...(host.value?.ports ?? []).map((p) => ({ key: `p${p}`, text: String(p), tone: 'accent' })),
]);
</script>

<template>
  <PopoverRoot v-if="known" v-model:open="open">
    <PopoverTrigger as-child>
      <button
        type="button"
        class="relative flex aspect-square min-w-0 items-center justify-center rounded-md border font-mono text-[0.72em] transition-[transform,border-color] duration-100 hover:-translate-y-px hover:border-fg-subtle focus-visible:z-10"
        :class="[tileClass, tile.isReserved && 'border-dashed', host?.is_monitored && !online && 'ring-2 ring-danger/40 ring-inset']"
        :style="lineStyle"
        :aria-label="label"
      >
        <span v-if="tile.group" class="absolute inset-x-0.5 top-0.5 h-[3px] rounded-full" :style="{ backgroundColor: tile.group.color }" aria-hidden="true" />
        <span v-if="showAreaLabel && tile.group" class="absolute -top-2 left-1 z-[1] max-w-[calc(100%*3)] truncate rounded-[3px] px-1 text-[9px] leading-[14px] font-semibold text-black" :style="{ backgroundColor: tile.group.color }" aria-hidden="true">
          {{ tile.group.name }}
        </span>
        <span v-if="emojiIcon" class="text-[1.4em]" :class="!online && 'opacity-50'" aria-hidden="true">{{ emojiIcon }}</span>
        <span v-else>{{ tile.i }}</span>
        <span class="absolute top-1 right-1 size-1.5 rounded-full" :class="online ? 'bg-accent' : 'bg-danger'" aria-hidden="true" />
        <Lock v-if="tile.isReserved" class="absolute right-0.5 bottom-0.5 size-2.5 text-info-text" aria-hidden="true" />
        <Eye v-if="host?.is_monitored" class="absolute bottom-0.5 left-0.5 size-2.5" :class="online ? 'text-info-text' : 'animate-pulse text-danger-text'" aria-hidden="true" />
      </button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent :side-offset="6" :collision-padding="12" class="z-50 w-72 rounded-lg border border-line bg-surface p-4 shadow-pop">
        <PopoverArrow class="fill-[var(--gl-surface)] stroke-[var(--gl-line)]" />
        <div class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-fg">{{ name }}</p>
            <p class="font-mono text-xs text-fg-subtle">{{ tile.ip }}</p>
          </div>
          <template v-if="device">
            <Button size="icon-sm" variant="ghost" :aria-pressed="!!device.is_reserved" :aria-label="device.is_reserved ? t('network.unreserve') : t('network.reserve')" :title="device.is_reserved ? t('network.unreserve') : t('network.reserve')" @click="emit('updateDevice', device.id, { is_reserved: !device.is_reserved })">
              <Lock v-if="device.is_reserved" class="text-info-text" aria-hidden="true" /><LockOpen v-else aria-hidden="true" />
            </Button>
          </template>
          <template v-else-if="host">
            <Button size="icon-sm" variant="ghost" :aria-pressed="!!host.is_reserved" :aria-label="host.is_reserved ? t('network.unreserve') : t('network.reserve')" :title="host.is_reserved ? t('network.unreserve') : t('network.reserve')" @click="emit('updateHost', host.id, { is_reserved: !host.is_reserved })">
              <Lock v-if="host.is_reserved" class="text-info-text" aria-hidden="true" /><LockOpen v-else aria-hidden="true" />
            </Button>
            <Button size="icon-sm" variant="ghost" :aria-pressed="!!host.is_monitored" :aria-label="host.is_monitored ? t('network.stop_monitoring') : t('network.start_monitoring')" :title="host.is_monitored ? t('network.stop_monitoring') : t('network.start_monitoring')" @click="emit('updateHost', host.id, { is_monitored: !host.is_monitored })">
              <Eye v-if="host.is_monitored" class="text-info-text" aria-hidden="true" /><EyeOff v-else aria-hidden="true" />
            </Button>
            <Button size="icon-sm" variant="danger-ghost" :aria-label="t('network.remove_from_list')" :title="t('network.remove_from_list')" @click="open = false; emit('deleteHost', host.id, tile.ip)">
              <Trash2 aria-hidden="true" />
            </Button>
          </template>
        </div>

        <dl class="mt-3 grid grid-cols-[4.5rem_1fr] gap-y-1 text-xs">
          <dt class="text-fg-subtle">MAC</dt><dd class="truncate font-mono text-fg">{{ device?.mac || host?.mac || 'N/A' }}</dd>
          <dt class="text-fg-subtle">Status</dt><dd :class="online ? 'text-accent-text' : 'text-danger-text'">{{ online ? t('network.online') : t('network.offline') }}</dd>
          <template v-if="device"><dt class="text-fg-subtle">{{ t('sidebar.dashboard') }}</dt><dd class="text-fg">{{ t('network.yes') }}</dd></template>
          <template v-if="tile.group"><dt class="text-fg-subtle">{{ t('network.area_name') }}</dt><dd class="flex items-center gap-1.5 text-fg"><span class="size-2 rounded-[3px]" :style="{ backgroundColor: tile.group.color }" />{{ tile.group.name }}</dd></template>
        </dl>

        <div v-if="device" class="mt-4 grid grid-cols-2 gap-2">
          <Button size="sm" @click="open = false; emit('openDevice', device)"><Info aria-hidden="true" />{{ t('editor.tabs.general') }}</Button>
          <Button size="sm" :loading="scanBusy" @click="emit('scanDevice', device.id, tile.ip)"><Activity v-if="!scanBusy" aria-hidden="true" />{{ t('network.nmap_scan') }}</Button>
        </div>
        <div v-else-if="host" class="mt-4 space-y-2">
          <form class="flex gap-2" @submit.prevent="emit('updateHost', host.id, { custom_name: customName })">
            <Input v-model="customName" class="h-8 text-xs" :placeholder="t('editor.custom_name_placeholder')" :aria-label="t('editor.custom_name_placeholder')" />
            <Button type="submit" size="icon-sm" :aria-label="t('common.save')"><Save aria-hidden="true" /></Button>
          </form>
          <div class="grid grid-cols-2 gap-2">
            <Button size="sm" variant="primary" :loading="addBusy" @click="emit('addDevice', tile.ip)"><Plus v-if="!addBusy" aria-hidden="true" />{{ t('network.status_on_dashboard') }}</Button>
            <Button size="sm" :loading="scanBusy" @click="emit('scanHost', tile.ip)"><Activity v-if="!scanBusy" aria-hidden="true" />{{ t('network.nmap_scan') }}</Button>
          </div>
        </div>

        <div v-if="ports.length > 0" class="mt-3 border-t border-line pt-3">
          <p class="gl-eyebrow mb-1.5">Services / {{ t('network.nmap_scan') }}</p>
          <div class="flex flex-wrap gap-1">
            <span v-for="p in ports" :key="p.key" class="rounded-sm px-1.5 py-0.5 font-mono text-[10px]" :class="p.tone === 'info' ? 'bg-info/10 text-info-text' : 'bg-accent/10 text-accent-text'">{{ p.text }}</span>
          </div>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>

  <div
    v-else
    class="relative flex aspect-square min-w-0 items-center justify-center rounded-md border font-mono text-[0.72em]"
    :class="tileClass"
    :title="label"
  >
    <span v-if="tile.group" class="absolute inset-x-0.5 top-0.5 h-[3px] rounded-full opacity-70" :style="{ backgroundColor: tile.group.color }" aria-hidden="true" />
    <span v-if="showAreaLabel && tile.group" class="absolute -top-2 left-1 z-[1] truncate rounded-[3px] px-1 text-[9px] leading-[14px] font-semibold text-black" :style="{ backgroundColor: tile.group.color }" aria-hidden="true">
      {{ tile.group.name }}
    </span>
    {{ tile.i }}
  </div>
</template>
