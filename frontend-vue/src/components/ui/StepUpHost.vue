<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ShieldCheck } from 'lucide-vue-next';
import Dialog from './Dialog.vue';
import Button from './Button.vue';
import Input from './Input.vue';
import { api } from '@/api/client';
import { pendingStepUp, settleStepUp } from '@/composables/useStepUp';
import { t } from '@/i18n';

/** The password dialog of a step-up: one class of actions, for the configured number of minutes. */
const password = ref('');
const error = ref<string | null>(null);
const busy = ref(false);
const minutes = ref(10);

const open = computed({
  get: () => pendingStepUp.value !== null,
  set: (value: boolean) => {
    if (!value) settleStepUp(false);
  },
});

// The password field takes the focus through its autofocus attribute (Dialog.vue)
watch(open, (isOpen) => {
  if (!isOpen) return;
  password.value = '';
  error.value = null;
  api.getStepUpStatus().then((s) => (minutes.value = s.minutes)).catch(() => {});
});

async function confirm() {
  const pending = pendingStepUp.value;
  if (!pending || !password.value || busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await api.stepUp(password.value, pending.scope);
    password.value = '';
    settleStepUp(true);
  } catch (err) {
    const status = (err as { status?: number }).status;
    error.value = status === 400 ? t('gv.stepup.wrong') : (err as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <Dialog v-model:open="open" :title="t('gv.stepup.title')" size="sm" top>
    <form class="space-y-3" @submit.prevent="confirm">
      <div class="flex gap-3">
        <span class="flex size-9 shrink-0 items-center justify-center rounded-md bg-warn/10 text-warn-text" aria-hidden="true">
          <ShieldCheck class="size-4" />
        </span>
        <div class="min-w-0 space-y-1 text-sm">
          <p class="font-medium text-fg">{{ pendingStepUp ? t(`gv.stepup.scope_${pendingStepUp.scope}`) : '' }}</p>
          <p class="text-fg-muted">{{ t('gv.stepup.hint', { minutes }) }}</p>
        </div>
      </div>
      <label class="block space-y-1.5">
        <span class="text-xs font-medium text-fg">{{ t('gv.stepup.password') }}</span>
        <Input
          v-model="password"
          type="password"
          autocomplete="current-password"
          autofocus
          :invalid="!!error"
          :aria-describedby="error ? 'stepup-error' : undefined"
        />
      </label>
      <p v-if="error" id="stepup-error" class="text-xs text-danger-text" role="alert">{{ error }}</p>
      <button type="submit" class="hidden" aria-hidden="true" tabindex="-1" />
    </form>
    <template #footer>
      <Button variant="ghost" :disabled="busy" @click="settleStepUp(false)">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :loading="busy" :disabled="!password" @click="confirm">{{ t('gv.stepup.confirm') }}</Button>
    </template>
  </Dialog>
</template>
