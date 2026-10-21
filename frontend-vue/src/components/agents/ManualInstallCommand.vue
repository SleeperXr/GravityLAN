<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Copy, RefreshCw } from 'lucide-vue-next';
import Button from '@/components/ui/Button.vue';
import { buildInstallCommand, buildUninstallCommand, requestInstallCode, type InstallCode } from '@/lib/agent';
import { copyText } from '@/lib/clipboard';
import { useToast } from '@/composables/useToast';
import { formatDateTime, t } from '@/i18n';

/**
 * The one-line installer (fresh single-use enrollment code) or uninstaller of a device.
 * Running it on the device installs/updates the agent; GravityLAN needs no SSH access for it.
 */
const props = withDefaults(defineProps<{ deviceId: number; mode?: 'install' | 'uninstall' }>(), { mode: 'install' });
const { showToast } = useToast();
const installCode = ref<InstallCode | null>(null);
const failed = ref(false);
const request = ref(0);

watch(
  () => [props.deviceId, props.mode, request.value] as const,
  async ([id, mode]) => {
    if (mode !== 'install') return;
    installCode.value = null;
    failed.value = false;
    try {
      installCode.value = await requestInstallCode(id);
    } catch {
      failed.value = true;
    }
  },
  { immediate: true },
);

const command = computed(() => {
  if (props.mode === 'uninstall') return buildUninstallCommand(props.deviceId);
  return installCode.value ? buildInstallCommand(props.deviceId, installCode.value.code) : '';
});

async function copy() {
  if (!command.value) return;
  if (await copyText(command.value)) showToast('success', t('notifications.copied'), t('notifications.copied_text'));
  else showToast('error', t('common.error'), t('settings.copy_failed'));
}
</script>

<template>
  <div class="space-y-2">
    <p class="text-xs leading-relaxed text-fg-muted">
      {{ mode === 'install' ? t('agent.manual_update_desc') : t('agent.manual_uninstall_desc') }}
    </p>
    <div class="flex items-stretch gap-2">
      <code
        class="min-w-0 flex-1 overflow-x-auto rounded-md border border-line bg-sunken px-3 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all"
        :class="mode === 'uninstall' ? 'text-danger-text' : 'text-fg'"
      >{{ command || t(failed ? 'agent.install_code_failed' : 'common.loading') }}</code>
      <Button size="sm" class="h-auto" :disabled="!command" @click="copy">
        <Copy aria-hidden="true" />
        {{ t('common.copy') }}
      </Button>
    </div>
    <div v-if="mode === 'install'" class="flex flex-wrap items-center justify-between gap-2 text-[11px] text-fg-subtle">
      <span>{{ installCode ? t('agent.install_code_hint', { time: formatDateTime(installCode.expiresAt, { hour: '2-digit', minute: '2-digit' }) }) : '' }}</span>
      <button type="button" class="inline-flex items-center gap-1 hover:text-fg" @click="request++">
        <RefreshCw class="size-3" aria-hidden="true" />
        {{ t('agent.install_code_retry') }}
      </button>
    </div>
  </div>
</template>
