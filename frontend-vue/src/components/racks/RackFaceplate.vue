<script setup lang="ts">
import { computed } from 'vue';
import { Bolt } from 'lucide-vue-next';
import { t } from '@/i18n';
import type { FaceLayout, JackSpot } from './rackGeometry';
import { kindOf } from './rackKinds';
import type { PortSide, RackEntry } from './rackModel';

/**
 * One faceplate, drawn as the hardware it stands for: mounting ears with a screw per unit, the network colour
 * of a device, a power LED that breathes while the device is online, and the jacks where its layout puts them.
 * Switches get link LEDs, servers drive bays at the front and power supplies at the rear, a UPS its display,
 * a blank its vent slots. Jacks are where cables start: pressing one begins a cable.
 */
const props = defineProps<{
  entry: RackEntry;
  side: PortSide;
  width: number;
  height: number;
  layout: FaceLayout;
  /** Colour of the cable on each cabled port */
  colourOfPort: Record<number, string>;
  /** Cabled ports whose other end (or this device) is offline */
  downPorts: ReadonlySet<number>;
  /** Where the cable of each cabled port goes ("Kabel zu sw-core · Port 5") */
  peerOfPort: Record<number, string>;
  /** Network colour of a device */
  accent: string | null;
  /** Ports on the other side of the rack, for a hint on this side */
  otherSidePorts: number;
  ambient: boolean;
  /** Ports to light up: the start of a new cable, the ends of the cable under the pointer, the jack a new cable would plug into */
  hotPorts: ReadonlySet<number>;
  pendingPortId: number | null;
}>();
const emit = defineEmits<{ jackDown: [portId: number, event: PointerEvent] }>();

const isDevice = computed(() => props.entry.kind === 'device');
const hasLed = computed(() => isDevice.value || props.entry.face === 'ups' || props.entry.face === 'phone');
const icon = computed(() => kindOf(props.entry.itemKind ?? 'other').icon);
const meta = computed(() => (isDevice.value ? props.entry.detail : t(`gv.rack.kind_${props.entry.itemKind ?? 'other'}`)));
/** Room between the label and the jacks, for decoration */
const room = computed(() => props.layout.jackLeft - props.layout.earPx - 12 - 140);
const inner = computed(() => Math.max(6, props.height - 8));

/**
 * Front: drive bays of a server or a storage box, as many as fit. They are wide, light caddies with a handle
 * next to the name plate, so they never pass for jacks: the dark holes on the right are the ports.
 */
/** "4 ports at the rear" only where it fits next to the name; the name always comes first */
const otherSideHint = computed(() => props.otherSidePorts > 0 && !props.layout.jacks.length && room.value > 90);
const bays = computed(() => {
  if (props.side !== 'front' || (props.entry.face !== 'server' && props.entry.face !== 'storage')) return null;
  const rows = props.entry.face === 'storage' ? Math.min(3, Math.max(1, props.entry.height)) : props.entry.height >= 2 ? 2 : 1;
  const perRow = Math.min(props.entry.face === 'storage' ? 4 : 3, Math.floor((room.value + 10 - (otherSideHint.value ? 96 : 0)) / 30));
  return perRow > 0 ? { rows, perRow, h: Math.max(3, (inner.value - (rows - 1) * 2) / rows) } : null;
});
/** Rear without ports: power supplies, and fans on a server */
const rearParts = computed(() => props.side === 'rear' && !props.layout.jacks.length && !['blank', 'cable', 'patch', 'fiber'].includes(props.entry.face) && room.value > 40);
const fans = computed(() => (rearParts.value && (props.entry.face === 'server' || props.entry.face === 'storage') && room.value > 110 ? 2 : 0));
const dRings = computed(() => (props.entry.face === 'cable' ? Math.max(2, Math.floor((props.width - 2 * props.layout.earPx - 150) / 46)) : 0));

const screwTops = computed(() => Array.from({ length: props.entry.height }, (_, i) => ((i + 0.5) / props.entry.height) * 100));

function jackTitle(jack: JackSpot): string {
  const state = props.peerOfPort[jack.portId] ?? (props.colourOfPort[jack.portId] ? t('gv.rack.ports_cabled') : t('gv.rack.ports_free'));
  return `${t('gv.rack.port')} ${jack.number} · ${jack.kind} · ${state}`;
}

/** A link LED fits above a single row of jacks that leaves room for it */
const ledRow = computed(() => {
  const first = props.layout.jacks[0];
  return Boolean(first && props.layout.jacks.every((j) => j.y === first.y) && first.y >= 4 && (props.entry.face === 'switch' || props.entry.face === 'router' || isDevice.value));
});
</script>

<template>
  <div class="rack-face" :class="[`face-${entry.face}`, !entry.online && 'is-offline', ambient && 'is-ambient']">
    <span class="rack-ear left-0" :style="{ width: `${layout.earPx}px` }" aria-hidden="true">
      <i v-for="top in screwTops" :key="top" class="rack-screw" :style="{ top: `${top}%` }" />
    </span>
    <span class="rack-ear right-0" :style="{ width: `${layout.earPx}px` }" aria-hidden="true">
      <i v-for="top in screwTops" :key="top" class="rack-screw" :style="{ top: `${top}%` }" />
    </span>
    <span v-if="accent" class="absolute top-[3px] bottom-[3px] w-[3px] rounded-full" :style="{ left: `${layout.earPx + 3}px`, backgroundColor: accent }" aria-hidden="true" />

    <div class="rack-face-body absolute inset-y-0 flex min-w-0 items-center gap-2" :style="{ left: `${layout.earPx + 10}px`, right: `${width - layout.jackLeft + 6}px` }">
      <span v-if="hasLed" class="rack-led" :class="entry.online ? 'is-on' : 'is-off'" aria-hidden="true" />
      <component :is="icon" v-else class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
      <!-- With drive bays the name plate has a fixed width, so the bays line up from one server to the next -->
      <span class="min-w-16 leading-tight" :class="bays ? 'shrink basis-32' : 'flex-1'">
        <span class="flex min-w-0 items-center gap-1.5">
          <span class="truncate text-xs font-semibold" :class="entry.face === 'blank' ? 'text-fg-subtle' : 'text-fg'" :title="entry.label">{{ entry.label }}</span>
          <span v-if="!entry.online" class="shrink-0 rounded-sm bg-danger/15 px-1 text-micro font-semibold text-danger-text">{{ t('network.offline') }}</span>
        </span>
        <span v-if="layout.twoLines" class="block truncate font-mono text-micro text-fg-subtle">{{ meta }}</span>
      </span>

      <span v-if="bays" class="flex shrink-0 flex-col gap-[2px]" aria-hidden="true">
        <span v-for="r in bays.rows" :key="r" class="flex gap-[4px]">
          <span v-for="b in bays.perRow" :key="b" class="rack-bay" :style="{ height: `${bays.h}px` }" />
        </span>
      </span>
      <span v-if="bays" class="flex-1" aria-hidden="true" />

      <span v-if="otherSideHint" class="shrink-0 font-mono text-micro text-fg-subtle">
        {{ t(side === 'front' ? 'gv.rack.ports_on_rear' : 'gv.rack.ports_on_front', { count: otherSidePorts }) }}
      </span>

      <span v-if="rearParts" class="flex shrink-0 items-center gap-1.5" aria-hidden="true">
        <span v-for="f in fans" :key="`fan-${f}`" class="rack-fan" :style="{ width: `${Math.min(inner, 18)}px`, height: `${Math.min(inner, 18)}px` }" />
        <span v-for="p in 2" :key="`psu-${p}`" class="rack-psu" :style="{ height: `${inner}px` }"><i class="rack-led is-small" :class="entry.online ? 'is-on' : 'is-idle'" /></span>
      </span>

      <span v-if="entry.face === 'ups' && side === 'front' && room > 20" class="rack-display" :style="{ height: `${Math.min(inner, 20)}px` }" aria-hidden="true">
        <Bolt class="size-3" :class="entry.online ? 'text-accent-text' : 'text-fg-subtle'" />
      </span>
      <span v-if="entry.face === 'phone' && side === 'front' && room > 20" class="rack-display w-10" :style="{ height: `${Math.min(inner, 16)}px` }" aria-hidden="true" />
      <span v-if="entry.face === 'power' && side === 'front' && room > 10" class="rack-rocker" :style="{ height: `${Math.min(inner, 14)}px` }" aria-hidden="true" />
      <span v-if="dRings" class="flex shrink-0 gap-6" aria-hidden="true">
        <span v-for="d in dRings" :key="d" class="rack-dring" :style="{ height: `${Math.min(inner, 12)}px` }" />
      </span>
    </div>

    <span
      v-for="jack in layout.jacks"
      :key="jack.portId"
      class="rack-jack"
      :class="[
        colourOfPort[jack.portId] && 'is-cabled',
        downPorts.has(jack.portId) && 'is-down',
        hotPorts.has(jack.portId) && 'is-hot',
        pendingPortId === jack.portId && 'is-pending',
      ]"
      :style="{
        left: `${jack.x}px`,
        top: `${jack.y}px`,
        width: `${jack.w}px`,
        height: `${jack.h}px`,
        '--plug': colourOfPort[jack.portId] ?? undefined,
      }"
      :data-port="jack.portId"
      :title="jackTitle(jack)"
      aria-hidden="true"
      @pointerdown.stop.prevent="emit('jackDown', jack.portId, $event)"
    >
      <i v-if="ledRow && colourOfPort[jack.portId]" class="rack-link" />
    </span>
  </div>
</template>

<style scoped>
.rack-face {
  --rack-face: var(--gl-raised);
  position: absolute;
  inset: 0;
  overflow: hidden;
  border: 1px solid var(--gl-line-strong);
  border-radius: 4px;
  background: var(--rack-face);
}
:root[data-theme='light'] .rack-face {
  --rack-face: var(--gl-surface);
}
.is-offline .rack-face-body {
  opacity: 0.75;
}
/* A blank is a plate with vent slots, cable management a darker strip with D-rings */
.face-blank {
  background-image: repeating-linear-gradient(90deg, transparent 0 9px, color-mix(in oklab, var(--gl-sunken) 85%, transparent) 9px 11px);
}
.face-cable {
  background: color-mix(in oklab, var(--rack-face) 55%, var(--gl-sunken));
}
.rack-ear {
  position: absolute;
  top: 0;
  bottom: 0;
  background: color-mix(in oklab, var(--gl-line-strong) 40%, var(--rack-face));
}
.rack-screw {
  position: absolute;
  left: 50%;
  width: 4px;
  height: 4px;
  margin: -2px 0 0 -2px;
  border-radius: 9999px;
  background: var(--gl-sunken);
  box-shadow: inset 0 0 0 1px var(--gl-line-strong);
}
.rack-led {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 9999px;
  background: var(--gl-line-strong);
}
.rack-led.is-small {
  width: 4px;
  height: 4px;
}
.rack-led.is-on {
  background: var(--gl-accent);
  box-shadow: 0 0 6px color-mix(in oklab, var(--gl-accent) 70%, transparent);
}
.rack-led.is-off {
  background: var(--gl-danger);
  box-shadow: 0 0 6px color-mix(in oklab, var(--gl-danger) 60%, transparent);
}
.is-ambient .rack-led.is-on {
  animation: rack-breathe 3.4s ease-in-out infinite;
}
@keyframes rack-breathe {
  50% {
    opacity: 0.4;
  }
}
/* A drive caddy: a light plate with its handle on the left, unlike a jack, which is a dark hole */
.rack-bay {
  width: 26px;
  border-radius: 2px;
  background: color-mix(in oklab, var(--gl-line-strong) 55%, var(--rack-face));
  box-shadow:
    inset 4px 0 0 color-mix(in oklab, var(--gl-fg-subtle) 45%, transparent),
    inset 0 1px 0 color-mix(in oklab, var(--gl-fg) 8%, transparent);
}
.rack-psu {
  display: flex;
  width: 26px;
  align-items: center;
  justify-content: flex-end;
  padding-right: 4px;
  border: 1px solid var(--gl-line-strong);
  border-radius: 2px;
  background: var(--gl-sunken);
}
.rack-fan {
  border: 1px solid var(--gl-line-strong);
  border-radius: 9999px;
  background: repeating-conic-gradient(from 0deg, var(--gl-sunken) 0 30deg, color-mix(in oklab, var(--gl-line-strong) 60%, var(--gl-sunken)) 30deg 45deg);
}
.rack-display {
  display: flex;
  width: 3.25rem;
  flex: none;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--gl-line-strong);
  border-radius: 3px;
  background: var(--gl-sunken);
}
/* The switch of a power strip: a red rocker, as on the real thing */
.rack-rocker {
  width: 10px;
  flex: none;
  border: 1px solid var(--gl-line-strong);
  border-radius: 2px;
  background: color-mix(in oklab, var(--gl-danger) 40%, var(--gl-sunken));
}
.rack-dring {
  width: 14px;
  border: 1.5px solid var(--gl-line-strong);
  border-top: none;
  border-radius: 0 0 7px 7px;
}
.rack-jack {
  position: absolute;
  z-index: 1;
  border: 1px solid var(--gl-line-strong);
  border-radius: 1.5px;
  background: var(--gl-sunken);
  cursor: crosshair;
  transition:
    transform 140ms var(--ease-out-expo),
    box-shadow 140ms ease-out;
}
.rack-jack.is-cabled {
  border-color: var(--plug);
  background: color-mix(in oklab, var(--plug) 80%, var(--gl-sunken));
}
.rack-jack.is-down {
  opacity: 0.55;
  border-style: dashed;
}
.rack-jack:hover,
.rack-jack.is-hot {
  z-index: 2;
  transform: scale(1.6);
  box-shadow: 0 0 0 1.5px var(--gl-accent);
}
.rack-jack.is-pending {
  z-index: 2;
  transform: scale(1.6);
  box-shadow: 0 0 0 2px var(--gl-warn);
  animation: rack-pending 1.1s ease-in-out infinite;
}
@keyframes rack-pending {
  50% {
    box-shadow: 0 0 0 4px color-mix(in oklab, var(--gl-warn) 35%, transparent);
  }
}
/* Link LED above a single row of jacks: lit while the cable's two ends are online */
.rack-link {
  position: absolute;
  top: -4px;
  left: 50%;
  width: 3px;
  height: 2px;
  margin-left: -1.5px;
  border-radius: 1px;
  background: var(--gl-accent);
}
.is-down .rack-link {
  background: var(--gl-warn);
}
</style>
