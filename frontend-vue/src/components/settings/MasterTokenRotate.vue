<script setup lang="ts">
import { ref } from 'vue';
import { CheckCircle2, Copy, RefreshCw } from 'lucide-vue-next';
import { api } from '@/api/client';
import Button from '@/components/ui/Button.vue';
import { copyText } from '@/lib/clipboard';
import { useConfirm } from '@/composables/useConfirm';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/** Replace the master token; the new one is shown here once, the server keeps only its hash. */
const { confirm } = useConfirm();
const { showToast } = useToast();
const busy = ref(false);
const created = ref('');

async function rotate() {
  const ok = await confirm({
    title: t('settings.password.master_token_confirm_title'),
    message: t('settings.password.master_token_confirm'),
    danger: true,
  });
  if (!ok) return;
  busy.value = true;
  created.value = '';
  try {
    created.value = (await api.rotateMasterToken()).token;
  } catch (err) {
    showToast('error', t('common.error'), `${t('settings.password.master_token_failed')} ${(err as Error).message}`);
  } finally {
    busy.value = false;
  }
}

async function copy() {
  if (await copyText(created.value)) showToast('success', t('common.success'), t('notifications.copied'));
  else showToast('error', t('common.error'), t('settings.copy_failed'));
}
</script>

<template>
  <div class="space-y-3 border-t border-line pt-4">
    <div>
      <p class="text-sm font-medium text-fg">{{ t('settings.password.master_token_title') }}</p>
      <p class="mt-1 max-w-prose text-xs text-fg-muted">{{ t('settings.password.master_token_desc') }}</p>
    </div>
    <Button variant="secondary" :loading="busy" data-test="rotate-master-token" @click="rotate">
      <RefreshCw v-if="!busy" aria-hidden="true" />{{ t('settings.password.master_token_rotate') }}
    </Button>
    <div v-if="created" role="status" data-test="master-token-created" class="space-y-2 rounded-md border border-accent/30 bg-accent/[0.07] p-3">
      <p class="flex items-center gap-2 text-sm text-fg"><CheckCircle2 class="size-4 text-accent-text" aria-hidden="true" />{{ t('settings.password.master_token_new') }}</p>
      <div class="flex gap-2">
        <input
          :value="created"
          readonly
          :aria-label="t('settings.password.master_token_title')"
          class="h-9 min-w-0 flex-1 rounded-md border border-line bg-sunken px-3 font-mono text-xs text-fg"
          @focus="($event.target as HTMLInputElement).select()"
        />
        <Button @click="copy"><Copy aria-hidden="true" />{{ t('settings.token_copy') }}</Button>
      </div>
    </div>
  </div>
</template>
