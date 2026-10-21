<script setup lang="ts">
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui';
import { X } from 'lucide-vue-next';
import { cn } from '@/lib/utils';
import { t } from '@/i18n';

/** Side drawer for detail views (device editor, health detail). Full screen on phones. */
const open = defineModel<boolean>('open', { default: false });
const props = withDefaults(defineProps<{ title: string; description?: string; width?: 'md' | 'lg' | 'xl'; class?: string }>(), {
  width: 'lg',
});

const widths = { md: 'md:max-w-md', lg: 'md:max-w-2xl', xl: 'md:max-w-4xl' };
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="gl-overlay fixed inset-0 z-50 bg-black/50" />
      <DialogContent
        :class="cn('gl-sheet fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-line bg-surface shadow-pop focus:outline-none', widths[props.width], props.class)"
      >
        <header class="flex items-start gap-3 border-b border-line px-5 pt-[max(1rem,env(safe-area-inset-top))] pb-4">
          <slot name="icon" />
          <div class="min-w-0 flex-1">
            <DialogTitle class="truncate text-base font-semibold text-fg">{{ props.title }}</DialogTitle>
            <DialogDescription class="mt-0.5 truncate text-sm text-fg-muted" :class="!props.description && 'sr-only'">
              {{ props.description || props.title }}
            </DialogDescription>
            <slot name="meta" />
          </div>
          <DialogClose
            class="-mt-1 -mr-2 inline-flex size-9 items-center justify-center rounded-md text-fg-subtle hover:bg-control-hover hover:text-fg"
            :aria-label="t('common.close')"
          >
            <X class="size-4" aria-hidden="true" />
          </DialogClose>
        </header>
        <slot name="tabs" />
        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style>
.gl-sheet[data-state='open'] {
  animation: gl-sheet-in 280ms var(--ease-out-expo);
}
.gl-sheet[data-state='closed'] {
  animation: gl-sheet-out 160ms ease-in;
}
@keyframes gl-sheet-in {
  from { transform: translateX(100%); }
}
@keyframes gl-sheet-out {
  to { transform: translateX(100%); }
}
</style>
