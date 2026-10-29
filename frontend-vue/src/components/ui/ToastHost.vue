<script setup lang="ts">
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-vue-next';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

const { toasts, removeToast, runToastAction } = useToast();
const icons = { success: CheckCircle2, error: AlertCircle, info: Info };
const tones = { success: 'text-accent-text', error: 'text-danger-text', info: 'text-info-text' };
</script>

<template>
  <section
    :aria-label="t('gv.toast.region')"
    class="pointer-events-none fixed inset-x-3 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-[60] flex flex-col items-end gap-2 md:inset-x-auto md:right-5 md:bottom-5 md:w-96"
  >
    <TransitionGroup name="gl-toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :role="toast.type === 'error' ? 'alert' : 'status'"
        class="pointer-events-auto flex w-full items-start gap-3 rounded-lg border border-line bg-surface p-3 shadow-pop"
      >
        <component :is="icons[toast.type]" class="mt-0.5 size-4 shrink-0" :class="tones[toast.type]" aria-hidden="true" />
        <div class="min-w-0 flex-1">
          <p class="text-sm font-medium text-fg">{{ toast.title }}</p>
          <p v-if="toast.message" class="mt-0.5 text-xs break-words text-fg-muted">{{ toast.message }}</p>
        </div>
        <button
          v-if="toast.action"
          type="button"
          class="-my-1 inline-flex h-7 shrink-0 items-center rounded-md px-2 text-xs font-semibold text-accent-text hover:bg-control-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          @click="runToastAction(toast.id)"
        >
          {{ toast.action.label }}
        </button>
        <button
          type="button"
          class="-m-1 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          :aria-label="t('common.close')"
          @click="removeToast(toast.id)"
        >
          <X class="size-3.5" aria-hidden="true" />
        </button>
      </div>
    </TransitionGroup>
  </section>
</template>

<style>
.gl-toast-enter-active {
  transition: opacity 200ms ease-out, transform 260ms var(--ease-out-expo);
}
.gl-toast-leave-active {
  transition: opacity 140ms ease-in;
}
.gl-toast-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.gl-toast-leave-to {
  opacity: 0;
}
</style>
