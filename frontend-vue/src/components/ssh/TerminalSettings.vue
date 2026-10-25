<script setup lang="ts">
import { computed, useId } from 'vue';
import { PopoverClose, PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui';
import { RotateCcw, Settings2, X } from 'lucide-vue-next';
import Button from '@/components/ui/Button.vue';
import Select from '@/components/ui/Select.vue';
import { FONT_OPTIONS, FONT_SIZE_MAX, FONT_SIZE_MIN, THEMES, resetTerminalPrefs, resolveTheme, setTerminalPrefs, terminalPrefs } from './terminalPrefs';
import { t } from '@/i18n';

/** Font, size and colours of the terminal; changes apply live to every open terminal. */
const id = useId();
const theme = computed(() => resolveTheme(terminalPrefs));
const fontCss = computed(() => FONT_OPTIONS.find((f) => f.id === terminalPrefs.fontFamily)?.css);

/** <input type="color"> only takes #rrggbb */
const toHex = (color: string | undefined, fallback: string) => (color && /^#[0-9a-f]{6}$/i.test(color) ? color : fallback);

const font = computed({ get: () => terminalPrefs.fontFamily, set: (v: string) => setTerminalPrefs({ fontFamily: v }) });
const themeId = computed({ get: () => terminalPrefs.theme, set: (v: string) => setTerminalPrefs({ theme: v, foreground: null, background: null }) });
</script>

<template>
  <PopoverRoot>
    <PopoverTrigger as-child>
      <Button size="icon-sm" variant="ghost" :aria-label="t('ssh.terminal.settings.title')" :title="t('ssh.terminal.settings.title')">
        <Settings2 aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        align="end"
        :side-offset="6"
        :collision-padding="12"
        class="z-50 w-80 max-w-[calc(100vw-24px)] space-y-4 rounded-lg border border-line bg-surface p-4 shadow-pop"
        :aria-labelledby="`${id}-title`"
      >
        <div class="flex items-center justify-between">
          <h3 :id="`${id}-title`" class="text-sm font-semibold text-fg">{{ t('ssh.terminal.settings.title') }}</h3>
          <PopoverClose class="inline-flex size-7 max-md:size-11 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg" :aria-label="t('common.close')">
            <X class="size-4" aria-hidden="true" />
          </PopoverClose>
        </div>

        <div class="space-y-1.5">
          <label :for="`${id}-font`" class="text-xs font-medium text-fg">{{ t('ssh.terminal.settings.font') }}</label>
          <Select :id="`${id}-font`" v-model="font" :options="FONT_OPTIONS.map((f) => ({ value: f.id, label: f.label }))" />
          <p class="text-xs text-fg-subtle">{{ t('ssh.terminal.settings.font_hint') }}</p>
        </div>

        <div class="space-y-1.5">
          <label :for="`${id}-size`" class="text-xs font-medium text-fg">{{ t('ssh.terminal.settings.size') }}: {{ terminalPrefs.fontSize }} px</label>
          <input
            :id="`${id}-size`"
            type="range"
            class="w-full accent-[var(--gl-accent)]"
            :min="FONT_SIZE_MIN"
            :max="FONT_SIZE_MAX"
            step="1"
            :value="terminalPrefs.fontSize"
            @input="setTerminalPrefs({ fontSize: Number(($event.target as HTMLInputElement).value) })"
          />
        </div>

        <div class="space-y-1.5">
          <label :for="`${id}-theme`" class="text-xs font-medium text-fg">{{ t('ssh.terminal.settings.theme') }}</label>
          <Select :id="`${id}-theme`" v-model="themeId" :options="THEMES.map((th) => ({ value: th.id, label: th.label }))" />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <label class="flex items-center justify-between gap-2 text-xs text-fg">
            {{ t('ssh.terminal.settings.text_color') }}
            <input type="color" class="h-7 w-10 cursor-pointer rounded border border-line bg-transparent" :value="toHex(theme.foreground, '#e8edf3')" @input="setTerminalPrefs({ foreground: ($event.target as HTMLInputElement).value })" />
          </label>
          <label class="flex items-center justify-between gap-2 text-xs text-fg">
            {{ t('ssh.terminal.settings.background') }}
            <input type="color" class="h-7 w-10 cursor-pointer rounded border border-line bg-transparent" :value="toHex(theme.background, '#080a0e')" @input="setTerminalPrefs({ background: ($event.target as HTMLInputElement).value })" />
          </label>
        </div>

        <div class="rounded-md border border-line px-3 py-2" :style="{ background: theme.background, color: theme.foreground, fontFamily: fontCss, fontSize: `${terminalPrefs.fontSize}px` }">
          root@server:~# ls -la
        </div>

        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-fg-subtle">{{ t('ssh.terminal.settings.saved_hint') }}</p>
          <Button size="sm" @click="resetTerminalPrefs"><RotateCcw aria-hidden="true" />{{ t('ssh.terminal.settings.reset') }}</Button>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
