<script setup lang="ts">
import { computed, ref } from 'vue';
import { Check, Download, Monitor, Trash2, Upload } from 'lucide-vue-next';
import ThemeSwatch from './ThemeSwatch.vue';
import Button from '@/components/ui/Button.vue';
import { useTheme, type ThemePreference } from '@/composables/useTheme';
import { useConfirm } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { THEMES, themeInfo } from '@/lib/themes';
import { MAX_DESIGNS, addCustomTheme, customPreview, customThemes, designTemplate, parseDesign, removeCustomTheme, type CustomTheme } from '@/lib/customThemes';
import { t } from '@/i18n';

/**
 * The design menu: every design as a card with a small preview, dark ones and light ones in
 * their own group, plus "System" (light or dark after the operating system) and the designs
 * uploaded in this browser. Used in the sidebar popover (`compact`: one column, no descriptions,
 * uploaded designs only to pick) and in Settings > Appearance (upload, template, remove).
 */
const props = defineProps<{ compact?: boolean }>();
const emit = defineEmits<{ picked: [] }>();
const { preference, resolved, activeCustom, setPreference } = useTheme();
const { confirm } = useConfirm();
const { showToast } = useToast();
const fileInput = ref<HTMLInputElement | null>(null);

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

async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  const result = parseDesign(await file.text());
  if (!result.ok) {
    showToast('error', t('gv.design.upload_failed'), t(`gv.design.error_${result.error.key}`, result.error.params));
    return;
  }
  const created = addCustomTheme(result.theme);
  setPreference(`custom:${created.id}`);
  showToast('success', t('gv.design.uploaded'), result.theme.name);
}

function downloadTemplate() {
  const name = activeCustom.value?.name ?? t(themeInfo(resolved.value).label);
  const base = activeCustom.value?.base ?? (themeInfo(resolved.value).scheme === 'light' ? 'light' : 'dark');
  const blob = new Blob([designTemplate(name, base)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `gravityui-design-${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'design'}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function remove(theme: CustomTheme) {
  const ok = await confirm({ title: t('gv.design.remove_title'), message: t('gv.design.remove_message', { name: theme.name }), confirmLabel: t('gv.design.remove'), danger: true });
  if (!ok) return;
  if (preference.value === `custom:${theme.id}`) setPreference(theme.base);
  removeCustomTheme(theme.id);
}
</script>

<template>
  <div role="radiogroup" :aria-label="t('gv.theme.label')" class="space-y-3">
    <button type="button" role="radio" :aria-checked="preference === 'system'" :class="[card, cardState(preference === 'system')]" @click="pick('system')">
      <!-- Half the day map, half the night map -->
      <!-- Each half is its design's ground with a bordered card, so the night half stays visible on a dark page -->
      <span class="flex h-9 w-14 shrink-0 overflow-hidden rounded-[5px] border border-line" aria-hidden="true">
        <span class="relative flex-1" :style="{ background: dayPreview.canvas }">
          <span class="absolute inset-y-1.5 right-0 left-1.5 rounded-l-[3px] border border-r-0" :style="{ background: dayPreview.surface, borderColor: dayPreview.line }" />
        </span>
        <span class="relative flex-1" :style="{ background: nightPreview.canvas }">
          <span class="absolute inset-y-1.5 right-1.5 left-0 rounded-r-[3px] border border-l-0" :style="{ background: nightPreview.surface, borderColor: nightPreview.line }" />
        </span>
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

    <div v-if="customThemes.length || !props.compact" role="group" :aria-label="t('gv.design.group')">
      <p class="mb-1.5 text-xs font-medium text-fg-subtle">{{ t('gv.design.group') }}</p>
      <div v-if="customThemes.length" class="grid gap-2" :class="props.compact ? 'grid-cols-1' : 'sm:grid-cols-2 xl:grid-cols-3'">
        <div v-for="theme in customThemes" :key="theme.id" class="flex items-stretch gap-1">
          <button
            type="button"
            role="radio"
            :aria-checked="preference === `custom:${theme.id}`"
            :class="[card, cardState(preference === `custom:${theme.id}`)]"
            @click="pick(`custom:${theme.id}`)"
          >
            <ThemeSwatch :preview="customPreview(theme)" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-medium text-fg">{{ theme.name }}</span>
              <span v-if="!props.compact" class="block text-xs text-fg-subtle">{{ t(theme.base === 'light' ? 'gv.design.based_on_light' : 'gv.design.based_on_dark') }}</span>
            </span>
            <Check v-if="preference === `custom:${theme.id}`" class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
          </button>
          <button
            v-if="!props.compact"
            type="button"
            class="inline-flex w-9 shrink-0 items-center justify-center rounded-md text-fg-subtle transition-colors hover:bg-danger/10 hover:text-danger-text"
            :aria-label="`${t('gv.design.remove')}: ${theme.name}`"
            :title="t('gv.design.remove')"
            @click="remove(theme)"
          >
            <Trash2 class="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      <template v-if="!props.compact">
        <p v-if="!customThemes.length" class="mb-2 max-w-prose text-xs text-fg-subtle">{{ t('gv.design.empty') }}</p>
        <div class="mt-2 flex flex-wrap gap-2">
          <Button size="sm" :disabled="customThemes.length >= MAX_DESIGNS" @click="fileInput?.click()"><Upload aria-hidden="true" />{{ t('gv.design.upload') }}</Button>
          <Button size="sm" variant="ghost" @click="downloadTemplate"><Download aria-hidden="true" />{{ t('gv.design.template') }}</Button>
          <input ref="fileInput" type="file" accept=".json,application/json" class="sr-only" tabindex="-1" aria-hidden="true" @change="upload" />
        </div>
        <p class="mt-1.5 max-w-prose text-xs text-fg-subtle">{{ t('gv.design.hint', { max: MAX_DESIGNS }) }}</p>
      </template>
    </div>
  </div>
</template>
