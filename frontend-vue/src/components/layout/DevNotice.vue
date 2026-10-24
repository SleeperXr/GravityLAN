<script setup lang="ts">
import { ref } from 'vue';
import { FlaskConical, X } from 'lucide-vue-next';
import { PROJECT_LINKS, REACT_UI_URL } from '@/lib/project';
import { t } from '@/i18n';

/** Thin strip saying GravityUI is still in development; closing it is remembered per browser. */
const STORAGE_KEY = 'gl.devNotice.dismissed';

function readDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

const dismissed = ref(readDismissed());

function dismiss() {
  dismissed.value = true;
  try {
    localStorage.setItem(STORAGE_KEY, '1');
  } catch {
    // private window or blocked storage: hidden until the next reload
  }
}
</script>

<template>
  <div v-if="!dismissed" role="note" class="flex shrink-0 items-center gap-2.5 border-b border-info/20 bg-info/[0.06] px-4 py-1.5 text-xs md:px-8">
    <FlaskConical class="size-3.5 shrink-0 text-info-text" aria-hidden="true" />
    <p class="min-w-0 flex-1 text-fg-muted">
      <span class="font-semibold text-fg">{{ t('gv.dev_notice.title') }}</span>
      <span class="hidden sm:inline">{{ ' ' + t('gv.dev_notice.text') }}</span>
      <a :href="REACT_UI_URL" class="ml-1.5 font-medium text-info-text underline-offset-2 hover:underline">{{ t('gv.dev_notice.classic') }}</a>
      <span class="text-fg-subtle" aria-hidden="true"> · </span>
      <a :href="PROJECT_LINKS.issues" target="_blank" rel="noopener noreferrer" class="font-medium text-info-text underline-offset-2 hover:underline">{{ t('gv.dev_notice.feedback') }}</a>
    </p>
    <button
      type="button"
      class="inline-flex size-6 shrink-0 items-center justify-center rounded text-fg-subtle hover:bg-control-hover hover:text-fg"
      :aria-label="t('gv.dev_notice.dismiss')"
      :title="t('gv.dev_notice.dismiss')"
      @click="dismiss"
    >
      <X class="size-3.5" aria-hidden="true" />
    </button>
  </div>
</template>
