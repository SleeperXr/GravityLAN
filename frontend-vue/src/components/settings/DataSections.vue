<script setup lang="ts">
import { ref } from 'vue';
import { AlertTriangle, Database, Download, Upload } from 'lucide-vue-next';
import { api } from '@/api/client';
import SettingsSection from './SettingsSection.vue';
import ActionRow from './ActionRow.vue';
import Button from '@/components/ui/Button.vue';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { useArmed } from '@/composables/useArmed';
import { t } from '@/i18n';

/** Backup export/import and the database reset (two-step button). */
const { showToast } = useToast();
const { confirm } = useConfirm();
const { armed, confirmOrArm } = useArmed<'reset'>();
const exporting = ref(false);
const importing = ref(false);

async function exportBackup() {
  exporting.value = true;
  try {
    const data = await api.exportBackup();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `gravitylan_backup_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    showToast('error', t('common.error'), t('settings.export_failed') + (err as Error).message);
  } finally {
    exporting.value = false;
  }
}

async function importBackup(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const ok = await confirm({ title: t('settings.backup_import'), message: t('settings.import_confirm_warning'), danger: true });
  if (!ok) {
    input.value = '';
    return;
  }
  importing.value = true;
  try {
    await api.importBackup(file);
    showToast('success', t('common.success'), t('settings.import_success'));
    window.setTimeout(() => window.location.reload(), 1200);
  } catch (err) {
    showToast('error', t('common.error'), t('settings.import_failed') + (err as Error).message);
  } finally {
    importing.value = false;
    input.value = '';
  }
}

async function resetDatabase() {
  if (!confirmOrArm('reset')) return;
  try {
    await api.resetDatabase();
    showToast('success', t('common.success'), t('settings.reset_success'));
    window.setTimeout(() => window.location.reload(), 1200);
  } catch (err) {
    showToast('error', t('common.error'), `${t('settings.reset_failed')}: ${(err as Error).message}`);
  }
}
</script>

<template>
  <SettingsSection id="backup" :title="t('settings.backup_restore')" :description="t('settings.section_backup_desc')">
    <div class="flex gap-2.5 rounded-md border border-warn/30 bg-warn/[0.07] p-3 text-sm">
      <AlertTriangle class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
      <p class="text-fg-muted"><strong class="text-fg">{{ t('settings.security_notice_title') }}:</strong> {{ t('settings.security_notice_desc') }}</p>
    </div>
    <ActionRow :title="t('settings.backup_export')" :description="t('settings.backup_export_desc')">
      <Button size="sm" :loading="exporting" @click="exportBackup"><Download v-if="!exporting" aria-hidden="true" />{{ exporting ? t('settings.backup_exporting') : t('settings.backup_download') }}</Button>
    </ActionRow>
    <ActionRow :title="t('settings.backup_import')" :description="t('settings.backup_import_desc')">
      <label class="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-line bg-control px-2.5 text-xs font-medium text-fg hover:border-line-strong hover:bg-control-hover focus-within:outline-2 focus-within:outline-info" :class="importing && 'pointer-events-none opacity-60'">
        <Upload class="size-4" aria-hidden="true" />
        {{ importing ? t('settings.backup_importing') : t('settings.backup_select_file') }}
        <input type="file" accept=".json,application/json" class="sr-only" :disabled="importing" @change="importBackup" />
      </label>
    </ActionRow>
  </SettingsSection>

  <SettingsSection id="danger" danger :title="t('settings.danger_zone')" :description="t('settings.section_danger_desc')">
    <ActionRow :title="t('settings.reset_db')" :description="t('settings.reset_warning')">
      <Button size="sm" :variant="armed === 'reset' ? 'danger' : 'danger-ghost'" :class="armed === 'reset' ? 'animate-pulse' : undefined" @click="resetDatabase">
        <Database aria-hidden="true" />{{ armed === 'reset' ? t('settings.reset_really') : t('settings.confirm_reset') }}
      </Button>
    </ActionRow>
  </SettingsSection>
</template>
