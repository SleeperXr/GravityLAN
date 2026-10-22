<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { Check, RotateCcw } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { Subnet } from '@/types';
import LineBullet from '@/components/common/LineBullet.vue';
import { lineLabel, networkColor } from '@/lib/networks';
import { useAppearance } from '@/stores/appearance';
import { useToast } from '@/composables/useToast';
import { useTheme } from '@/composables/useTheme';
import { t } from '@/i18n';

/**
 * One line colour per network, used on the network map, line signs, device chips and racks.
 * Saved right away (setting `ui.line_colors`); "Network colour" goes back to the palette slot.
 */
const appearance = useAppearance();
const { showToast } = useToast();
const subnets = ref<Subnet[]>([]);
const loaded = ref(false);

onMounted(async () => {
  await appearance.load();
  try {
    subnets.value = (await api.getSubnetsList()).sort((a, b) => (a.vlan_id ?? 0) - (b.vlan_id ?? 0) || a.cidr.localeCompare(b.cidr));
  } catch {
    subnets.value = [];
  } finally {
    loaded.value = true;
  }
});

// The palette as concrete colours of the current theme (a custom colour is stored as #rrggbb)
const { resolved: theme } = useTheme();
const palette = computed(() => {
  void theme.value; // light and dark have their own palette
  const style = getComputedStyle(document.documentElement);
  return Array.from({ length: 10 }, (_, i) => style.getPropertyValue(`--line-${i + 1}`).trim()).filter((c) => /^#[0-9a-f]{6}$/i.test(c));
});

const bullet = (s: Subnet) => lineLabel(s);
const custom = (s: Subnet) => appearance.lineColors[String(s.id)] ?? null;
const toHex = (color: string | null) => (color && /^#[0-9a-f]{6}$/i.test(color) ? color : '#2ec4a6');

async function choose(s: Subnet, color: string | null) {
  try {
    await appearance.setLineColor(s.id, color);
  } catch (err) {
    showToast('error', t('gv.lines.colors_title'), (err as Error).message);
  }
}
</script>

<template>
  <fieldset class="mt-6 border-t border-line pt-5">
    <legend class="sr-only">{{ t('gv.lines.colors_title') }}</legend>
    <p class="text-sm font-semibold text-fg">{{ t('gv.lines.colors_title') }}</p>
    <p class="mt-0.5 text-xs leading-relaxed text-fg-subtle">{{ t('gv.lines.colors_desc') }}</p>

    <p v-if="loaded && subnets.length === 0" class="mt-3 text-xs text-fg-subtle">{{ t('gv.lines.colors_empty') }}</p>
    <ul v-else class="mt-3 divide-y divide-line">
      <li v-for="s in subnets" :key="s.id" class="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
        <span class="flex min-w-0 flex-1 basis-48 items-center gap-3">
          <LineBullet :color="networkColor(s.id)" :label="bullet(s)" />
          <span class="min-w-0">
            <span class="block truncate text-sm font-medium text-fg">{{ s.name || s.cidr }}</span>
            <span class="block font-mono text-[11px] text-fg-subtle">{{ s.cidr }}<template v-if="s.vlan_id != null"> · VLAN {{ s.vlan_id }}</template></span>
          </span>
        </span>
        <span class="flex flex-wrap items-center gap-1.5" role="group" :aria-label="t('gv.lines.colors_for', { name: s.name || s.cidr })">
          <button
            v-for="(color, i) in palette"
            :key="color"
            type="button"
            class="grid size-6 place-items-center rounded-full ring-offset-2 ring-offset-surface transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-fg"
            :style="{ background: color }"
            :aria-label="t('gv.lines.slot', { n: i + 1 })"
            :aria-pressed="custom(s)?.toLowerCase() === color.toLowerCase()"
            @click="choose(s, color)"
          >
            <Check v-if="custom(s)?.toLowerCase() === color.toLowerCase()" class="size-3.5 text-[#0c0f14]" :stroke-width="3" aria-hidden="true" />
          </button>
          <label class="relative grid size-6 cursor-pointer place-items-center overflow-hidden rounded-full border border-dashed border-line-strong" :title="t('gv.lines.custom')">
            <span class="sr-only">{{ t('gv.lines.custom') }}</span>
            <span class="text-[11px] font-bold text-fg-subtle" aria-hidden="true">+</span>
            <input type="color" class="absolute inset-0 cursor-pointer opacity-0" :value="toHex(custom(s))" @change="choose(s, ($event.target as HTMLInputElement).value)" />
          </label>
          <button
            type="button"
            class="ml-1 inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors disabled:opacity-40"
            :class="custom(s) ? 'text-fg-muted hover:bg-control-hover hover:text-fg' : 'text-fg-subtle'"
            :disabled="!custom(s)"
            @click="choose(s, null)"
          >
            <RotateCcw class="size-3.5" aria-hidden="true" />{{ t('gv.lines.reset') }}
          </button>
        </span>
      </li>
    </ul>
  </fieldset>
</template>
