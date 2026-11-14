<script setup lang="ts">
import { computed, ref } from 'vue';
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui';
import { ChevronUp, LogOut } from 'lucide-vue-next';
import { api } from '@/api/client';
import { useTheme } from '@/composables/useTheme';
import { themeInfo } from '@/lib/themes';
import ThemePicker from '@/components/settings/ThemePicker.vue';
import ThemeSwatch from '@/components/settings/ThemeSwatch.vue';
import { locale, setLocale, t, type Locale } from '@/i18n';

/** Design menu, language and sign-out: shared by sidebar footer and phone menu. */
const { preference, resolved } = useTheme();
const designOpen = ref(false);
const currentLabel = computed(() => (preference.value === 'system' ? `${t('gv.theme.system')} · ${t(themeInfo(resolved.value).label)}` : t(themeInfo(resolved.value).label)));
const locales: { value: Locale; label: string }[] = [
  { value: 'de', label: 'DE' },
  { value: 'en', label: 'EN' },
];

async function logout() {
  await api.logout().catch(() => {});
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex gap-2">
      <!-- The design menu: one button with the current design, the cards open above it -->
      <PopoverRoot v-model:open="designOpen">
        <PopoverTrigger
          class="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-sunken pr-2 pl-1 text-left text-xs transition-colors hover:border-line-strong max-md:h-11"
          :aria-label="`${t('gv.theme.menu')}: ${currentLabel}`"
        >
          <ThemeSwatch :preview="themeInfo(resolved).preview" small />
          <span class="min-w-0 flex-1 truncate font-medium text-fg">{{ currentLabel }}</span>
          <ChevronUp class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent side="top" align="start" :side-offset="8" :collision-padding="12" class="z-50 w-72 rounded-lg border border-line bg-popover p-3 shadow-pop">
            <p class="mb-2.5 text-sm font-semibold text-fg">{{ t('gv.theme.menu') }}</p>
            <ThemePicker compact @picked="designOpen = false" />
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>
      <div role="radiogroup" :aria-label="t('gv.language')" class="flex rounded-md border border-line bg-sunken p-0.5">
        <button
          v-for="opt in locales"
          :key="opt.value"
          type="button"
          role="radio"
          :aria-checked="locale === opt.value"
          class="h-8 rounded-[5px] px-2 font-mono text-xs font-semibold transition-colors"
          :class="locale === opt.value ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          @click="setLocale(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>
    <button
      type="button"
      class="flex h-9 w-full items-center justify-center gap-2 rounded-md border border-line bg-control text-xs font-medium text-fg-subtle transition-colors hover:border-danger/40 hover:text-danger-text"
      @click="logout"
    >
      <LogOut class="size-4" aria-hidden="true" />
      {{ t('gv.logout') }}
    </button>
  </div>
</template>
