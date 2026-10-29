<script setup lang="ts">
import { computed } from 'vue';
import { ArrowLeftRight, LogOut, Monitor, Moon, Sun } from 'lucide-vue-next';
import { api } from '@/api/client';
import { useTheme, type ThemePreference } from '@/composables/useTheme';
import { locale, setLocale, t, type Locale } from '@/i18n';

/** Theme, language, switch to the React UI and sign-out: shared by sidebar footer and phone menu. */
const { preference, setPreference } = useTheme();

const themes = computed<{ value: ThemePreference; label: string; icon: typeof Sun }[]>(() => [
  { value: 'system', label: t('gv.theme.system'), icon: Monitor },
  { value: 'light', label: t('gv.theme.light'), icon: Sun },
  { value: 'dark', label: t('gv.theme.dark'), icon: Moon },
]);
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
      <div role="radiogroup" :aria-label="t('gv.theme.label')" class="flex flex-1 rounded-md border border-line bg-sunken p-0.5">
        <button
          v-for="opt in themes"
          :key="opt.value"
          type="button"
          role="radio"
          :aria-checked="preference === opt.value"
          :aria-label="opt.label"
          :title="opt.label"
          class="flex h-8 flex-1 items-center justify-center rounded-[5px] transition-colors"
          :class="preference === opt.value ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          @click="setPreference(opt.value)"
        >
          <component :is="opt.icon" class="size-4" aria-hidden="true" />
        </button>
      </div>
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
    <div class="flex gap-2">
      <a
        href="/?ui=react"
        :title="t('gv.legacy.switch_hint')"
        class="flex h-9 flex-1 items-center gap-2 rounded-md border border-line bg-control px-3 text-xs font-medium text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
      >
        <ArrowLeftRight class="size-3.5 text-accent-text" aria-hidden="true" />
        <span class="flex-1 truncate">{{ t('gv.legacy.switch') }}</span>
        <span class="rounded-sm border border-line px-1 font-mono text-micro text-fg-subtle">{{ t('gv.legacy.badge') }}</span>
      </a>
      <button
        type="button"
        :aria-label="t('gv.logout')"
        :title="t('gv.logout')"
        class="flex size-9 items-center justify-center rounded-md border border-line bg-control text-fg-subtle transition-colors hover:border-danger/40 hover:text-danger-text"
        @click="logout"
      >
        <LogOut class="size-4" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
