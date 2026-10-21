<script setup lang="ts">
import { AlertTriangle, RotateCw } from 'lucide-vue-next';
import Button from './Button.vue';
import { t } from '@/i18n';

defineProps<{ title?: string; message?: string | null; retrying?: boolean }>();
const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <div role="alert" class="flex flex-col items-center gap-3 px-6 py-12 text-center">
    <div class="flex size-11 items-center justify-center rounded-lg border border-danger/30 bg-danger/10 text-danger-text">
      <AlertTriangle class="size-5" aria-hidden="true" />
    </div>
    <div class="max-w-md space-y-1">
      <p class="text-sm font-semibold text-fg">{{ title || t('gv.state.load_failed') }}</p>
      <p v-if="message" class="font-mono text-xs break-words text-fg-muted">{{ message }}</p>
    </div>
    <Button size="sm" :loading="retrying" @click="emit('retry')">
      <RotateCw v-if="!retrying" aria-hidden="true" />
      {{ t('common.retry') }}
    </Button>
  </div>
</template>
