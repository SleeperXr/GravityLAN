<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { Check, RotateCcw } from 'lucide-vue-next';
import { LINK_TYPES } from '@/components/orbit/orbitModel';
import { useAppearance } from '@/stores/appearance';
import { useToast } from '@/composables/useToast';
import { useTheme } from '@/composables/useTheme';
import { t } from '@/i18n';
import { linePaletteHex } from '@/lib/palette';

/**
 * One beam colour per connection type (10GbE, 2.5GbE, 1GbE, 100Mb, WLAN, fibre) on the orbit map.
 * Saved right away (setting `ui.link_type_colors`); a colour set on a single link still wins,
 * and without a type colour a beam keeps its network's colour.
 */
const appearance = useAppearance();
const { showToast } = useToast();
onMounted(() => void appearance.load());

const { resolved: theme } = useTheme();
const palette = computed(() => {
  void theme.value;
  return linePaletteHex();
});

const custom = (type: string) => appearance.linkTypeColors[type] ?? null;
const toHex = (color: string | null) => (color && /^#[0-9a-f]{6}$/i.test(color) ? color : '#2ec4a6');
const label = (type: string) => (type === 'Fiber' ? t('gv.link_types.fiber') : type);

async function choose(type: string, color: string | null) {
  try {
    await appearance.setLinkTypeColor(type, color);
  } catch (err) {
    showToast('error', t('gv.link_types.title'), (err as Error).message);
  }
}
</script>

<template>
  <fieldset class="mt-6 border-t border-line pt-5">
    <legend class="sr-only">{{ t('gv.link_types.title') }}</legend>
    <p class="text-sm font-semibold text-fg">{{ t('gv.link_types.title') }}</p>
    <p class="mt-0.5 max-w-prose text-xs leading-relaxed text-fg-subtle">{{ t('gv.link_types.desc') }}</p>

    <ul class="mt-3 divide-y divide-line">
      <li v-for="type in LINK_TYPES" :key="type" class="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
        <span class="flex min-w-0 flex-1 basis-48 items-center gap-3">
          <svg width="36" height="10" viewBox="0 0 36 10" aria-hidden="true" class="shrink-0">
            <line x1="2" y1="5" x2="34" y2="5" :stroke="custom(type) ?? 'var(--gl-fg-subtle)'" stroke-width="3" stroke-linecap="round" :stroke-dasharray="type === 'WLAN' ? '5 4' : undefined" />
          </svg>
          <span class="min-w-0">
            <span class="block truncate font-mono text-sm font-medium text-fg">{{ label(type) }}</span>
            <span class="block text-xs text-fg-subtle">{{ custom(type) ? custom(type) : t('gv.link_types.network') }}</span>
          </span>
        </span>
        <span class="flex flex-wrap items-center gap-1.5" role="group" :aria-label="t('gv.link_types.for', { type: label(type) })">
          <button
            v-for="(color, i) in palette"
            :key="color"
            type="button"
            class="grid size-6 place-items-center rounded-full ring-offset-2 ring-offset-surface transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-fg"
            :style="{ background: color }"
            :aria-label="t('gv.lines.slot', { n: i + 1 })"
            :aria-pressed="custom(type)?.toLowerCase() === color.toLowerCase()"
            @click="choose(type, color)"
          >
            <Check v-if="custom(type)?.toLowerCase() === color.toLowerCase()" class="size-3.5 text-[#0c0f14]" :stroke-width="3" aria-hidden="true" />
          </button>
          <label class="relative grid size-6 cursor-pointer place-items-center overflow-hidden rounded-full border border-dashed border-line-strong" :title="t('gv.lines.custom')">
            <span class="sr-only">{{ t('gv.lines.custom') }}</span>
            <span class="text-xs font-bold text-fg-subtle" aria-hidden="true">+</span>
            <input type="color" class="absolute inset-0 cursor-pointer opacity-0" :value="toHex(custom(type))" @change="choose(type, ($event.target as HTMLInputElement).value)" />
          </label>
          <button
            type="button"
            class="ml-1 inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors disabled:opacity-40"
            :class="custom(type) ? 'text-fg-muted hover:bg-control-hover hover:text-fg' : 'text-fg-subtle'"
            :disabled="!custom(type)"
            @click="choose(type, null)"
          >
            <RotateCcw class="size-3.5" aria-hidden="true" />{{ t('gv.link_types.reset') }}
          </button>
        </span>
      </li>
    </ul>
  </fieldset>
</template>
