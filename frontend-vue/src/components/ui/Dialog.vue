<script setup lang="ts">
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui';
import { X } from 'lucide-vue-next';
import { cn } from '@/lib/utils';
import { t } from '@/i18n';

/**
 * Modal dialog. Centered on desktop, a bottom sheet on phones. Focus trap, Escape and
 * scroll lock come from reka-ui.
 */
const open = defineModel<boolean>('open', { default: false });
const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    size?: 'sm' | 'md' | 'lg' | 'xl';
    class?: string;
    /**
     * Above every other dialog and sheet (confirmations). A dialog mounted once at app start sits
     * earlier in the DOM than a sheet opened later, so at the same z-index it would end up behind it.
     */
    top?: boolean;
  }>(),
  { size: 'md', top: false },
);

const widths = { sm: 'sm:max-w-sm', md: 'sm:max-w-lg', lg: 'sm:max-w-2xl', xl: 'sm:max-w-4xl' };

/**
 * reka-ui focuses the first tabbable element on open, which is the close button. A field marked
 * `autofocus` is where the dialog wants the user to start, so it gets the focus instead.
 */
function focusAutofocusField(event: Event) {
  const content = event.target instanceof HTMLElement ? event.target : null;
  const field = content?.querySelector<HTMLElement>('[autofocus]');
  if (!field) return;
  event.preventDefault();
  field.focus();
}
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="gl-overlay fixed inset-0 bg-black/55 backdrop-blur-[2px]" :class="props.top ? 'z-[55]' : 'z-50'" />
      <DialogContent
        :class="
          cn(
            props.top ? 'z-[55]' : 'z-50',
            'gl-dialog fixed flex max-h-[92dvh] w-full flex-col border border-line bg-surface shadow-pop focus:outline-none',
            'inset-x-0 bottom-0 rounded-t-xl pb-[env(safe-area-inset-bottom)]',
            'sm:inset-x-auto sm:bottom-auto sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:pb-0',
            widths[props.size],
            props.class,
          )
        "
        @open-auto-focus="focusAutofocusField"
      >
        <header class="flex items-start gap-3 border-b border-line px-5 py-4">
          <div class="min-w-0 flex-1">
            <DialogTitle class="text-base font-semibold text-fg">{{ props.title }}</DialogTitle>
            <DialogDescription v-if="props.description" class="mt-1 text-sm text-fg-muted">
              {{ props.description }}
            </DialogDescription>
            <DialogDescription v-else class="sr-only">{{ props.title }}</DialogDescription>
          </div>
          <DialogClose
            class="-mt-1 -mr-2 inline-flex size-8 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg"
            :aria-label="t('common.close')"
          >
            <X class="size-4" aria-hidden="true" />
          </DialogClose>
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style>
.gl-overlay[data-state='open'] {
  animation: gl-fade-in 160ms ease-out;
}
.gl-overlay[data-state='closed'] {
  animation: gl-fade-out 120ms ease-in;
}
.gl-dialog[data-state='open'] {
  animation: gl-dialog-in 220ms var(--ease-out-expo);
}
.gl-dialog[data-state='closed'] {
  animation: gl-fade-out 120ms ease-in;
}
@media (max-width: 639px) {
  .gl-dialog[data-state='open'] {
    animation: gl-sheet-up 260ms var(--ease-out-expo);
  }
}
@keyframes gl-fade-in {
  from { opacity: 0; }
}
@keyframes gl-fade-out {
  to { opacity: 0; }
}
@keyframes gl-dialog-in {
  from { opacity: 0; transform: translate(-50%, calc(-50% + 6px)) scale(0.98); }
}
@keyframes gl-sheet-up {
  from { transform: translateY(100%); }
}
</style>
