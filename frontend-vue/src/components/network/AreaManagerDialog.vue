<script setup lang="ts">
import { ref, watch } from 'vue';
import { Plus, Trash2 } from 'lucide-vue-next';
import type { NetworkArea } from '@/lib/subnetModel';
import Dialog from '@/components/ui/Dialog.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';
import { linePaletteHex, nextPaletteColour } from '@/lib/palette';

/** Named address ranges (.start–.end) of the shown /24; saved together on "Save". */
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ areas: NetworkArea[]; prefix: string }>();
const emit = defineEmits<{ save: [areas: NetworkArea[]] }>();

/** A new area takes the first line colour no area of this /24 uses yet */
const blankArea = (taken: NetworkArea[]): NetworkArea => ({
  name: '',
  start: 0,
  end: 0,
  color: nextPaletteColour(
    taken.map((a) => a.color),
    linePaletteHex(),
  ),
});
const local = ref<NetworkArea[]>([]);
const draft = ref<NetworkArea>(blankArea([]));

watch(open, (isOpen) => {
  if (!isOpen) return;
  local.value = props.areas.map((a) => ({ ...a }));
  draft.value = blankArea(local.value);
});

const num = (v: unknown) => Math.max(0, Math.min(255, parseInt(String(v), 10) || 0));

function addDraft() {
  if (!draft.value.name.trim() && !draft.value.start && !draft.value.end) return;
  local.value = [...local.value, { ...draft.value }];
  draft.value = blankArea(local.value);
}

function save() {
  const final = draft.value.name.trim() ? [...local.value, { ...draft.value }] : local.value;
  draft.value = blankArea(final);
  emit('save', final);
  open.value = false;
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('network.manage_areas')" :description="`${prefix}.0/24`" size="lg">
    <div class="hidden grid-cols-[1fr_5rem_5rem_3rem_2.25rem] gap-2 px-1 pb-1.5 text-xs font-medium text-fg-subtle sm:grid">
      <span>{{ t('network.area_name') }}</span><span>{{ t('network.start') }}</span><span>{{ t('network.end') }}</span><span>{{ t('network.color') }}</span><span />
    </div>
    <form class="grid grid-cols-[1fr_4.5rem_4.5rem] gap-2 rounded-md border border-dashed border-line-strong p-2 sm:grid-cols-[1fr_5rem_5rem_3rem_2.25rem]" @submit.prevent="addDraft">
      <Input v-model="draft.name" class="col-span-3 sm:col-span-1" :placeholder="t('network.area_name')" :aria-label="t('network.area_name')" />
      <Input :model-value="draft.start || ''" type="number" min="0" max="255" mono :placeholder="t('network.start')" :aria-label="t('network.start')" @update:model-value="(v) => (draft.start = num(v))" />
      <Input :model-value="draft.end || ''" type="number" min="0" max="255" mono :placeholder="t('network.end')" :aria-label="t('network.end')" @update:model-value="(v) => (draft.end = num(v))" />
      <input v-model="draft.color" type="color" class="h-9 w-full cursor-pointer rounded-md border border-line bg-sunken p-1" :aria-label="t('network.color')" />
      <Button type="submit" variant="primary" size="icon" :aria-label="t('network.add_new')"><Plus aria-hidden="true" /></Button>
    </form>

    <ul class="mt-3 max-h-[50dvh] space-y-2 overflow-y-auto">
      <li v-for="(area, idx) in local" :key="idx" class="grid grid-cols-[1fr_4.5rem_4.5rem] items-center gap-2 rounded-md border border-line bg-raised p-2 sm:grid-cols-[1fr_5rem_5rem_3rem_2.25rem]">
        <Input v-model="area.name" class="col-span-3 sm:col-span-1" :aria-label="t('network.area_name')" />
        <Input :model-value="area.start" type="number" min="0" max="255" mono :aria-label="t('network.start')" @update:model-value="(v) => (area.start = num(v))" />
        <Input :model-value="area.end" type="number" min="0" max="255" mono :aria-label="t('network.end')" @update:model-value="(v) => (area.end = num(v))" />
        <input v-model="area.color" type="color" class="h-9 w-full cursor-pointer rounded-md border border-line bg-sunken p-1" :aria-label="t('network.color')" />
        <Button size="icon" variant="danger-ghost" :aria-label="`${t('common.delete')}: ${area.name}`" @click="local = local.filter((_, i) => i !== idx)"><Trash2 aria-hidden="true" /></Button>
      </li>
    </ul>
    <template #footer>
      <Button variant="ghost" @click="open = false">{{ t('common.cancel') }}</Button>
      <Button variant="primary" @click="save">{{ t('common.save') }}</Button>
    </template>
  </Dialog>
</template>
