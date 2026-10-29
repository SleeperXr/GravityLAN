<script setup lang="ts">
import { AlertCircle, Bell, BellOff, CheckCircle2, Info, Trash2 } from 'lucide-vue-next';
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui';
import Button from '@/components/ui/Button.vue';
import { useToast } from '@/composables/useToast';
import { formatDateTime, t } from '@/i18n';

/** Bell with the toast history of this browser session. */
const { history, clearHistory } = useToast();
const icons = { success: CheckCircle2, error: AlertCircle, info: Info };
const tones = { success: 'text-accent-text', error: 'text-danger-text', info: 'text-info-text' };
</script>

<template>
  <PopoverRoot>
    <PopoverTrigger as-child>
      <Button size="icon" :aria-label="history.length ? `${t('notifications.title')} (${history.length})` : t('notifications.title')" :title="t('notifications.title')" class="relative">
        <Bell aria-hidden="true" />
        <span
          v-if="history.length > 0"
          class="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-info px-1 font-mono text-micro font-semibold text-canvas"
          aria-hidden="true"
        >
          {{ history.length > 9 ? '9+' : history.length }}
        </span>
      </Button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        align="end"
        :side-offset="8"
        class="z-50 flex max-h-[min(32rem,70dvh)] w-[min(24rem,calc(100vw-1.5rem))] flex-col rounded-lg border border-line bg-surface shadow-pop"
      >
        <div class="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold text-fg"><Bell class="size-4" aria-hidden="true" />{{ t('notifications.title') }}</h2>
          <Button v-if="history.length > 0" size="sm" variant="danger-ghost" @click="clearHistory">
            <Trash2 aria-hidden="true" />{{ t('notifications.clear_all') }}
          </Button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <div v-if="history.length === 0" class="flex flex-col items-center gap-3 px-6 py-12 text-center text-sm text-fg-subtle">
            <BellOff class="size-8 opacity-40" aria-hidden="true" />
            {{ t('notifications.no_notifications') }}
          </div>
          <ul v-else class="divide-y divide-line">
            <li v-for="toast in history" :key="toast.id" class="flex gap-3 px-4 py-3">
              <component :is="icons[toast.type]" class="mt-0.5 size-4 shrink-0" :class="tones[toast.type]" aria-hidden="true" />
              <div class="min-w-0 flex-1">
                <p class="text-sm font-medium text-fg">{{ toast.title }}</p>
                <p v-if="toast.message" class="mt-0.5 text-xs leading-relaxed break-words text-fg-muted">{{ toast.message }}</p>
                <p class="mt-1 font-mono text-xs text-fg-subtle">{{ formatDateTime(toast.timestamp, { timeStyle: 'medium' }) }}</p>
              </div>
            </li>
          </ul>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
