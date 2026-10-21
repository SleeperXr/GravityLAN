<script setup lang="ts">
import { computed } from 'vue';
import Dialog from './Dialog.vue';
import Button from './Button.vue';
import { pendingConfirm, settleConfirm } from '@/composables/useConfirm';
import { t } from '@/i18n';

const open = computed({
  get: () => pendingConfirm.value !== null,
  set: (value: boolean) => {
    if (!value) settleConfirm(false);
  },
});
</script>

<template>
  <Dialog v-model:open="open" :title="pendingConfirm?.title ?? ''" size="sm">
    <p v-if="pendingConfirm?.message" class="text-sm leading-relaxed whitespace-pre-line text-fg-muted">{{ pendingConfirm.message }}</p>
    <template #footer>
      <Button variant="ghost" @click="settleConfirm(false)">{{ pendingConfirm?.cancelLabel || t('common.cancel') }}</Button>
      <Button :variant="pendingConfirm?.danger ? 'danger' : 'primary'" @click="settleConfirm(true)">
        {{ pendingConfirm?.confirmLabel || t('common.confirm') }}
      </Button>
    </template>
  </Dialog>
</template>
