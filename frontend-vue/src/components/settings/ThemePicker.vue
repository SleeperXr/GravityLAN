<script setup lang="ts">
import { computed } from 'vue';
import { Check, Monitor } from 'lucide-vue-next';
import ThemeSwatch from './ThemeSwatch.vue';
import { useTheme, type ThemePreference } from '@/composables/useTheme';
import { THEMES, themeInfo } from '@/lib/themes';
import { t } from '@/i18n';

/**
 * The design menu: every design as a card with a small preview, dark ones and light ones in
 * their own group, plus "System" (light or dark after the operating system). Used in the sidebar
 * popover (`compact`: one column, no descriptions) and in Settings > Appearance.
 */
const props = defineProps<{ compact?: boolean }>();
const emit = defineEmits<{ picked: [] }>();
const { preference, setPreference } = useTheme();

const groups = computed(() => [
  { key: 'dark', label: t('gv.theme.group_dark'), themes: THEMES.filter((th) => th.scheme === 'dark') },
  { key: 'light', label: t('gv.theme.group_light'), themes: THEMES.filter((th) => th.scheme === 'light') },
]);

function pick(value: ThemePreference) {
  setPreference(value);
  emit('picked');
}

const dayPreview = themeInfo('light').preview;
const nightPreview = themeInfo('dark').preview;
const card = 'flex w-full items-center gap-3 rounded-md border p-2 text-left transition-colors';
const cardState = (on: boolean) => (on ? 'border-accent bg-accent/10' : 'border-line hover:border-line-strong hover:bg-hover');
</script>

<template>
  <div role="radiogroup" :aria-label="t('gv.theme.label')" class="space-y-3">
    <button type="button" role="radio" :aria-checked="preference === 'system'" :class="[card, cardState(preference === 'system')]" @click="pick('system')">
      <!-- Half the day map, half the night map -->
      <span class="flex h-9 w-14 shrink-0 overflow-hidden rounded-[5px] border border-line" aria-hidden="true">
        <span class="flex-1" :style="{ background: dayPreview.surface }" />
        <span class="flex-1" :style="{ background: nightPreview.surface }" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-1.5 text-sm font-medium text-fg"><Monitor class="size-3.5 text-fg-subtle" aria-hidden="true" />{{ t('gv.theme.system') }}</span>
        <span v-if="!props.compact" class="block text-xs text-fg-subtle">{{ t('gv.theme.system_desc') }}</span>
      </span>
      <Check v-if="preference === 'system'" class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
    </button>

    <div v-for="group in groups" :key="group.key" role="group" :aria-label="group.label">
      <p class="mb-1.5 text-xs font-medium text-fg-subtle">{{ group.label }}</p>
      <div class="grid gap-2" :class="props.compact ? 'grid-cols-1' : 'sm:grid-cols-2 xl:grid-cols-3'">
        <button
          v-for="theme in group.themes"
          :key="theme.id"
          type="button"
          role="radio"
          :aria-checked="preference === theme.id"
          :class="[card, cardState(preference === theme.id)]"
          @click="pick(theme.id)"
        >
          <ThemeSwatch :preview="theme.preview" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium text-fg">{{ t(theme.label) }}</span>
            <span v-if="!props.compact" class="block text-xs text-fg-subtle">{{ t(theme.description) }}</span>
          </span>
          <Check v-if="preference === theme.id" class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
        </button>
      </div>
    </div>
  </div>
</template>
