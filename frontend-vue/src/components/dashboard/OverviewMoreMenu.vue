<script setup lang="ts">
import { ref } from 'vue';
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui';
import { Ellipsis, Pencil, RefreshCw } from 'lucide-vue-next';
import Button from '@/components/ui/Button.vue';
import { t } from '@/i18n';

/**
 * The overview's less frequent actions on a phone, with their names: as a row of bare icons with
 * numbers ("5", pencil, arrows) nobody could tell them apart.
 */
defineProps<{ updates: number; refreshing: boolean; scanning: boolean }>();
const emit = defineEmits<{ updates: []; edit: []; refresh: [] }>();

const open = ref(false);
function pick(action: 'updates' | 'edit' | 'refresh') {
  open.value = false;
  if (action === 'updates') emit('updates');
  else if (action === 'edit') emit('edit');
  else emit('refresh');
}

const item = 'flex min-h-11 w-full items-center gap-3 px-4 text-left text-sm text-fg transition-colors hover:bg-raised disabled:opacity-50';
</script>

<template>
  <PopoverRoot v-model:open="open">
    <PopoverTrigger as-child>
      <Button size="icon" class="relative" :aria-label="t('gv.dashboard.more_actions')" :title="t('gv.dashboard.more_actions')">
        <Ellipsis aria-hidden="true" />
        <span v-if="updates > 0" class="absolute -top-0.5 -right-0.5 size-2.5 rounded-full border-2 border-canvas bg-warn" aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent align="end" :side-offset="8" class="z-50 w-64 overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-pop">
        <button v-if="updates > 0" type="button" :class="[item, 'text-warn-text']" @click="pick('updates')">
          <RefreshCw class="size-4 shrink-0" aria-hidden="true" />
          <span class="flex-1">{{ t('dashboard.agent_updates') }}</span>
          <span class="font-mono text-xs tabular">{{ updates }}</span>
        </button>
        <button type="button" :class="item" @click="pick('edit')">
          <Pencil class="size-4 shrink-0 text-fg-subtle" aria-hidden="true" />{{ t('dashboard.edit_layout') }}
        </button>
        <button type="button" :class="item" :disabled="refreshing || scanning" @click="pick('refresh')">
          <RefreshCw class="size-4 shrink-0 text-fg-subtle" :class="refreshing && 'animate-spin'" aria-hidden="true" />{{ refreshing ? t('dashboard.refreshing') : t('dashboard.refresh_all') }}
        </button>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
