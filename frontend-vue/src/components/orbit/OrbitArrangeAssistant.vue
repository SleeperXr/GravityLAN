<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Wand2 } from 'lucide-vue-next';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Select from '@/components/ui/Select.vue';
import Input from '@/components/ui/Input.vue';
import Tabs from '@/components/ui/Tabs.vue';
import { deviceLabel } from '@/lib/networks';
import { t } from '@/i18n';
import type { OrbitBody, OrbitLink, OrbitRoles } from './orbitModel';
import {
  ARRANGE_KINDS,
  detectedKind,
  effectiveKind,
  isHubKind,
  matchesSearch,
  planArrange,
  type ArrangeKind,
  type ArrangePlan,
} from './orbitArrange';

/**
 * "Build the network" before arranging: say what each device is (router, switch, access point, host, client),
 * which hub each switch, AP or host hangs on, and which clients hang on which hub. The parent applies the plan
 * (roles and links) and then lays the map out; "Only arrange" keeps the old one-click behaviour.
 */
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ bodies: Map<number, OrbitBody>; links: OrbitLink[]; roles: OrbitRoles; busy?: boolean }>();
const emit = defineEmits<{ apply: [plan: ArrangePlan]; arrangeOnly: [] }>();

const step = ref('kinds');
const kinds = ref<Record<number, ArrangeKind>>({});
const parents = ref<Record<number, number>>({});
const search = ref('');
const target = ref<number | null>(null);
const picked = ref<Set<number>>(new Set());
const onlyUnassigned = ref(true);

watch(open, (now) => {
  if (!now) return;
  step.value = 'kinds';
  kinds.value = {};
  parents.value = {};
  search.value = '';
  picked.value = new Set();
  target.value = null;
});

const list = computed(() => [...props.bodies.values()].sort((a, b) => deviceLabel(a.device).localeCompare(deviceLabel(b.device))));
const kindOf = (b: OrbitBody) => effectiveKind(kinds.value[b.id], b);
const kindLabel = (b: OrbitBody) => t(`gv.arrange.kind_${kindOf(b)}`);
const filtered = (items: OrbitBody[]) => items.filter((b) => matchesSearch(b.device, search.value));
const nameOf = (id: number | null | undefined) => {
  const body = id == null ? undefined : props.bodies.get(id);
  return body ? deviceLabel(body.device) : '';
};

const kindOptions = (b: OrbitBody) =>
  ARRANGE_KINDS.map((k) => ({
    value: k,
    label: k === 'auto' ? t('gv.arrange.kind_auto', { kind: t(`gv.arrange.kind_${detectedKind(b)}`) }) : t(`gv.arrange.kind_${k}`),
  }));
function setKind(b: OrbitBody, value: ArrangeKind) {
  kinds.value = { ...kinds.value, [b.id]: value };
}

/** Stars and hubs as they will be after step 1: what a device can hang on */
const hubs = computed(() => list.value.filter((b) => kindOf(b) === 'star' || isHubKind(kindOf(b))));
const hubBodies = computed(() => hubs.value.filter((b) => kindOf(b) !== 'star'));
const clients = computed(() => list.value.filter((b) => kindOf(b) === 'client'));
const hubOption = (h: OrbitBody) => ({ value: h.id as number | null, label: `${deviceLabel(h.device)} · ${kindLabel(h)}` });

const uplinkOptions = (b: OrbitBody) => [
  { value: null as number | null, label: t('gv.arrange.uplink_keep') },
  ...hubs.value.filter((h) => h.id !== b.id).map(hubOption),
];
function setUplink(b: OrbitBody, value: number | null) {
  const next = { ...parents.value };
  if (value == null) delete next[b.id];
  else next[b.id] = value;
  parents.value = next;
}

const targetOptions = computed(() => [{ value: null as number | null, label: t('gv.arrange.pick_hub') }, ...hubs.value.map(hubOption)]);
/** A client still on the router with nothing chosen counts as unassigned */
const unassigned = (b: OrbitBody) =>
  parents.value[b.id] == null && (b.parentId == null || props.bodies.get(b.parentId)?.kind === 'star');
const clientRows = computed(() => filtered(clients.value).filter((b) => !onlyUnassigned.value || unassigned(b)));
function togglePick(id: number) {
  const next = new Set(picked.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  picked.value = next;
}
function assignPicked() {
  if (target.value == null) return;
  const next = { ...parents.value };
  for (const id of picked.value) if (id !== target.value) next[id] = target.value;
  parents.value = next;
  picked.value = new Set();
}
const assigned = computed(() => {
  const counts = new Map<number, number>();
  for (const p of Object.values(parents.value)) counts.set(p, (counts.get(p) ?? 0) + 1);
  return [...counts].map(([id, n]) => ({ id, name: nameOf(id), n }));
});

const plan = computed(() => planArrange(props.bodies, props.links, props.roles, { kinds: kinds.value, parents: parents.value }));
const changes = computed(() => plan.value.createLinks.length + plan.value.removeLinkIds.length + Object.keys(kinds.value).length);

const tabs = computed(() => [
  { value: 'kinds', label: t('gv.arrange.step_kinds') },
  { value: 'uplinks', label: t('gv.arrange.step_uplinks'), badge: hubBodies.value.length },
  { value: 'clients', label: t('gv.arrange.step_clients'), badge: clients.value.length },
]);
</script>

<template>
  <Dialog v-model:open="open" :title="t('gv.arrange.title')" :description="t('gv.arrange.description')" size="xl">
    <!-- A steady height: switching steps or filtering must not make the dialog jump -->
    <div class="flex min-h-0 flex-col gap-3 sm:min-h-[66dvh]">
      <Input v-model="search" :placeholder="t('gv.arrange.search')" data-test="arrange-search" />
      <Tabs v-model="step" :tabs="tabs" :label="t('gv.arrange.title')">
        <template #kinds>
          <p class="py-2 text-xs text-fg-subtle">{{ t('gv.arrange.kinds_hint') }}</p>
          <ul class="max-h-[50dvh] divide-y divide-line overflow-y-auto" data-test="arrange-kinds">
            <li v-for="b in filtered(list)" :key="b.id" class="flex items-center gap-3 py-1.5">
              <span class="min-w-0 flex-1 truncate text-sm">
                {{ deviceLabel(b.device) }} <span class="font-mono text-xs text-fg-subtle">{{ b.device.ip }}</span>
              </span>
              <Select
                class="w-56 shrink-0"
                :model-value="kinds[b.id] ?? 'auto'"
                :options="kindOptions(b)"
                :aria-label="t('gv.arrange.kind_of', { name: deviceLabel(b.device) })"
                @update:model-value="(v) => setKind(b, v as ArrangeKind)"
              />
            </li>
          </ul>
        </template>

        <template #uplinks>
          <p class="py-2 text-xs text-fg-subtle">{{ t('gv.arrange.uplinks_hint') }}</p>
          <p v-if="!hubBodies.length" class="py-6 text-center text-sm text-fg-subtle">{{ t('gv.arrange.no_hubs') }}</p>
          <ul v-else class="max-h-[50dvh] divide-y divide-line overflow-y-auto" data-test="arrange-uplinks">
            <li v-for="b in filtered(hubBodies)" :key="b.id" class="flex items-center gap-3 py-1.5">
              <span class="min-w-0 flex-1 truncate text-sm">
                {{ deviceLabel(b.device) }} <span class="text-xs text-fg-subtle">{{ kindLabel(b) }}</span>
                <span v-if="b.parentId != null && parents[b.id] == null" class="block truncate text-xs text-fg-subtle">
                  {{ t('gv.arrange.now_on', { name: nameOf(b.parentId) }) }}
                </span>
              </span>
              <Select
                class="w-64 shrink-0"
                :model-value="parents[b.id] ?? null"
                :options="uplinkOptions(b)"
                :aria-label="t('gv.arrange.uplink_of', { name: deviceLabel(b.device) })"
                @update:model-value="(v) => setUplink(b, v as number | null)"
              />
            </li>
          </ul>
        </template>

        <template #clients>
          <div class="flex flex-wrap items-center gap-2 py-2">
            <Select v-model="target" class="w-64" :options="targetOptions" :aria-label="t('gv.arrange.pick_hub')" data-test="arrange-target" />
            <Button size="sm" :disabled="target == null || !picked.size" data-test="arrange-assign" @click="assignPicked">
              {{ t('gv.arrange.assign', { n: picked.size }) }}
            </Button>
            <label class="ml-auto flex items-center gap-2 text-xs text-fg-subtle">
              <input v-model="onlyUnassigned" type="checkbox" /> {{ t('gv.arrange.only_unassigned') }}
            </label>
          </div>
          <p class="pb-2 text-xs text-fg-subtle">{{ t('gv.arrange.clients_hint') }}</p>
          <ul class="max-h-[44dvh] divide-y divide-line overflow-y-auto" data-test="arrange-clients">
            <li v-for="b in clientRows" :key="b.id">
              <label class="flex cursor-pointer items-center gap-3 py-1.5">
                <input type="checkbox" :checked="picked.has(b.id)" @change="togglePick(b.id)" />
                <span class="min-w-0 flex-1 truncate text-sm">
                  {{ deviceLabel(b.device) }} <span class="font-mono text-xs text-fg-subtle">{{ b.device.ip }}</span>
                </span>
                <span v-if="parents[b.id] != null" class="truncate text-xs text-fg-subtle">→ {{ nameOf(parents[b.id]) }}</span>
              </label>
            </li>
            <li v-if="!clientRows.length" class="py-6 text-center text-sm text-fg-subtle">{{ t('gv.arrange.no_clients') }}</li>
          </ul>
          <p v-if="assigned.length" class="pt-2 text-xs text-fg-subtle">
            <span v-for="a in assigned" :key="a.id" class="mr-3">{{ a.name }}: {{ a.n }}</span>
          </p>
        </template>
      </Tabs>
    </div>

    <template #footer>
      <div class="flex w-full flex-wrap items-center gap-2">
        <span class="text-xs text-fg-subtle" data-test="arrange-summary">
          {{ t('gv.arrange.summary', { links: plan.createLinks.length, removed: plan.removeLinkIds.length, roles: Object.keys(kinds).length }) }}
        </span>
        <span class="flex-1" />
        <Button variant="ghost" size="sm" :disabled="props.busy" data-test="arrange-only" @click="emit('arrangeOnly')">
          {{ t('gv.arrange.only_arrange') }}
        </Button>
        <Button size="sm" :disabled="props.busy || !changes" data-test="arrange-apply" @click="emit('apply', plan)">
          <Wand2 aria-hidden="true" />{{ t('gv.arrange.apply') }}
        </Button>
      </div>
    </template>
  </Dialog>
</template>
