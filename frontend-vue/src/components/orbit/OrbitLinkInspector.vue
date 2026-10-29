<script setup lang="ts">
import { Plus, Trash2, X } from 'lucide-vue-next';
import { isBackupLink, linkTypeOptions, type LinkRole, type OrbitLink } from './orbitModel';
import Button from '@/components/ui/Button.vue';
import { t } from '@/i18n';

/** Edit mode: colour, role (primary or backup), type and removal of the selected light beam. */
defineProps<{ link: OrbitLink; ends: string; swatches: string[] }>();
const emit = defineEmits<{ patch: [patch: Partial<OrbitLink>]; remove: []; close: [] }>();
const roles: LinkRole[] = ['primary', 'backup'];
</script>

<template>
  <div class="absolute bottom-3 left-3 z-10 w-[min(22rem,calc(100%-4.5rem))] space-y-3 rounded-lg border border-line-strong bg-surface p-3.5 shadow-pop" role="dialog" :aria-label="t('gv.plan.link')" @pointerdown.stop>
    <div class="flex items-start gap-2">
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">{{ t('gv.plan.link') }}</p>
        <p class="truncate text-xs text-fg-subtle">{{ ends }}</p>
      </div>
      <button type="button" class="-m-1 inline-flex size-7 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover" :aria-label="t('common.close')" @click="emit('close')">
        <X class="size-4" />
      </button>
    </div>
    <fieldset>
      <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('gv.plan.line_color') }}</legend>
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          class="h-7 rounded-full border border-line-strong px-2.5 text-xs font-medium"
          :class="!link.color ? 'bg-fg text-canvas' : 'text-fg-muted hover:text-fg'"
          :aria-pressed="!link.color"
          @click="emit('patch', { color: null })"
        >
          {{ t('gv.plan.network_color') }}
        </button>
        <button
          v-for="(c, i) in swatches"
          :key="c"
          type="button"
          class="size-7 rounded-full ring-offset-2 ring-offset-surface transition-transform hover:scale-110"
          :class="link.color?.toLowerCase() === c.toLowerCase() && 'ring-2 ring-fg'"
          :style="{ backgroundColor: c }"
          :aria-label="t('gv.lines.slot', { n: i + 1 })"
          :aria-pressed="link.color?.toLowerCase() === c.toLowerCase()"
          @click="emit('patch', { color: c })"
        />
        <label class="relative size-7 cursor-pointer overflow-hidden rounded-full border border-dashed border-line-strong" :title="t('gv.plan.custom_color')">
          <span class="sr-only">{{ t('gv.plan.custom_color') }}</span>
          <input type="color" class="absolute inset-0 size-full cursor-pointer opacity-0" :value="link.color ?? '#2ec4a6'" @change="emit('patch', { color: ($event.target as HTMLInputElement).value })" />
          <Plus class="absolute inset-0 m-auto size-3.5 text-fg-subtle" aria-hidden="true" />
        </label>
      </div>
    </fieldset>
    <fieldset>
      <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('gv.plan.link_role') }}</legend>
      <div class="flex rounded-md border border-line bg-sunken p-0.5">
        <button
          v-for="role in roles"
          :key="role"
          type="button"
          class="h-8 flex-1 rounded-[5px] text-xs font-semibold transition-colors"
          :class="(role === 'backup') === isBackupLink(link) ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="(role === 'backup') === isBackupLink(link)"
          @click="emit('patch', { role })"
        >
          {{ t(`gv.plan.role_${role}`) }}
        </button>
      </div>
      <p class="mt-1 text-xs text-fg-subtle">{{ t('gv.plan.role_hint') }}</p>
    </fieldset>
    <div class="flex items-end gap-2">
      <label class="flex flex-1 flex-col gap-1.5 text-xs font-medium text-fg">
        {{ t('gv.plan.link_type') }}
        <select
          :value="link.link_type"
          class="h-9 rounded-md border border-line bg-sunken px-2 text-sm text-fg focus:border-accent focus:outline-none"
          @change="emit('patch', { link_type: ($event.target as HTMLSelectElement).value })"
        >
          <option v-for="lt in linkTypeOptions(link.link_type)" :key="lt" :value="lt">{{ lt }}</option>
        </select>
      </label>
      <Button variant="danger-ghost" @click="emit('remove')"><Trash2 aria-hidden="true" />{{ t('common.delete') }}</Button>
    </div>
  </div>
</template>
