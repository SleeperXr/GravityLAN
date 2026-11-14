<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { AlertTriangle, CheckCircle2, RefreshCw, Server, Trash2 } from 'lucide-vue-next';
import { api, type ProxmoxReport as Report, type ProxmoxSettings } from '@/api/client';
import ProxmoxReport from './ProxmoxReport.vue';
import SettingsSection from './SettingsSection.vue';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import Switch from '@/components/ui/Switch.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { t } from '@/i18n';

/**
 * Settings > Proxmox VE: read guest names and addresses through the Proxmox API.
 * The token secret is write-only; an empty field keeps the stored one.
 */
const { showToast } = useToast();
const { confirm } = useConfirm();

const stored = ref<ProxmoxSettings | null>(null);
const report = ref<Report | null>(null);
const form = ref({ enabled: false, url: '', token_id: '', token_secret: '', verify_tls: true });
const saving = ref(false);
const syncing = ref(false);

function applyStored(next: ProxmoxSettings) {
  stored.value = next;
  form.value = { enabled: next.enabled, url: next.url, token_id: next.token_id, token_secret: '', verify_tls: next.verify_tls };
}

function loadReport() {
  api.getProxmoxReport().then((res) => (report.value = res.report)).catch(() => {});
}

onMounted(() => {
  api.getProxmoxSettings().then(applyStored).catch(() => {});
  loadReport();
});

const configured = computed(() => !!stored.value && (stored.value.has_token_secret || !!stored.value.url));
const isDirty = computed(() => {
  const s = stored.value;
  if (!s) return false;
  const f = form.value;
  return f.enabled !== s.enabled || f.url !== s.url || f.token_id !== s.token_id || f.verify_tls !== s.verify_tls || f.token_secret !== '';
});
/** A stored secret only travels to the server and token ID it was entered for. */
const targetChanged = computed(
  () => !!stored.value?.has_token_secret && (form.value.url.trim().replace(/\/+$/, '') !== stored.value.url || form.value.token_id.trim() !== stored.value.token_id),
);
const needsSecret = computed(() => !form.value.token_secret && (targetChanged.value || (form.value.enabled && !stored.value?.has_token_secret)));
const canSave = computed(() => isDirty.value && !needsSecret.value && (!form.value.enabled || (!!form.value.url.trim() && !!form.value.token_id.trim())));
const canSync = computed(() => !!stored.value?.enabled && !isDirty.value);

async function save() {
  saving.value = true;
  try {
    const { token_secret, ...rest } = form.value;
    applyStored(await api.saveProxmoxSettings({ ...rest, ...(token_secret ? { token_secret } : {}) }));
    showToast('success', t('common.success'), t('gv.proxmox.saved'));
  } catch (err) {
    showToast('error', t('common.error'), `${t('gv.proxmox.save_failed')} ${(err as Error).message}`);
  } finally {
    saving.value = false;
  }
}

async function sync() {
  syncing.value = true;
  try {
    const res = await api.syncProxmox();
    // An empty list is usually a token without permissions, not an empty cluster
    if (res.guests === 0 && res.skipped === 0) showToast('info', t('gv.proxmox.synced_title'), t('gv.proxmox.no_guests'));
    else showToast('success', t('gv.proxmox.synced_title'), t('gv.proxmox.synced_body', { ...res }));
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    syncing.value = false;
    // The form may hold unsaved edits by now; only the status line follows the server
    api.getProxmoxSettings().then((next) => (stored.value = next)).catch(() => {});
    loadReport();
  }
}

async function disconnect() {
  const ok = await confirm({ title: t('gv.proxmox.disconnect_title'), message: t('gv.proxmox.disconnect_message'), danger: true });
  if (!ok) return;
  try {
    await api.deleteProxmoxSettings();
    report.value = null;
    applyStored(await api.getProxmoxSettings());
    showToast('success', t('common.success'), t('gv.proxmox.disconnected'));
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  }
}
</script>

<template>
  <SettingsSection id="proxmox" :title="t('gv.proxmox.title')" :description="t('gv.proxmox.description')">
    <!-- Where the last sync stands -->
    <p v-if="stored?.last_error" role="status" class="flex items-start gap-2 text-sm text-danger-text" data-test="proxmox-error">
      <AlertTriangle class="mt-0.5 size-4 shrink-0" aria-hidden="true" />{{ stored.last_error }}
    </p>
    <p v-else-if="stored?.last_sync" role="status" class="flex items-center gap-1.5 text-sm text-fg-muted">
      <CheckCircle2 class="size-4 shrink-0 text-accent-text" aria-hidden="true" />{{ t('gv.proxmox.last_sync') }} <RelativeTime :date="stored.last_sync" />
    </p>

    <form class="space-y-4" @submit.prevent="save">
      <label class="flex cursor-pointer items-center gap-3">
        <span class="min-w-0 flex-1">
          <span class="block text-sm font-medium text-fg">{{ t('gv.proxmox.enabled') }}</span>
          <span id="proxmox-enabled-hint" class="block text-xs text-fg-subtle">{{ t('gv.proxmox.enabled_hint') }}</span>
        </span>
        <Switch v-model="form.enabled" :aria-label="t('gv.proxmox.enabled')" aria-describedby="proxmox-enabled-hint" />
      </label>

      <div class="grid gap-4 md:grid-cols-2">
        <Field v-slot="{ id, describedBy }" :label="t('gv.proxmox.url')" :hint="t('gv.proxmox.url_hint')">
          <Input :id="id" v-model="form.url" mono type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://pve.lan:8006" :aria-describedby="describedBy" data-test="proxmox-url" />
        </Field>
        <Field v-slot="{ id, describedBy }" :label="t('gv.proxmox.token_id')" :hint="t('gv.proxmox.token_id_hint')">
          <Input :id="id" v-model="form.token_id" mono autocomplete="off" spellcheck="false" placeholder="gravitylan@pve!inventory" :aria-describedby="describedBy" data-test="proxmox-token-id" />
        </Field>
        <Field
          v-slot="{ id, describedBy, invalid }"
          :label="t('gv.proxmox.secret')"
          :hint="stored?.has_token_secret ? t('gv.proxmox.secret_stored') : t('gv.proxmox.secret_hint')"
          :error="targetChanged && !form.token_secret ? t('gv.proxmox.secret_reenter') : null"
        >
          <Input
            :id="id"
            v-model="form.token_secret"
            mono
            type="password"
            autocomplete="new-password"
            spellcheck="false"
            :placeholder="stored?.has_token_secret && !targetChanged ? '••••••••' : ''"
            :aria-describedby="describedBy"
            :invalid="invalid"
            data-test="proxmox-secret"
          />
        </Field>
      </div>

      <label class="flex cursor-pointer items-center gap-3">
        <span class="min-w-0 flex-1">
          <span class="block text-sm font-medium text-fg">{{ t('gv.proxmox.ignore_tls') }}</span>
          <span id="proxmox-tls-hint" class="block text-xs text-fg-subtle">{{ t('gv.proxmox.ignore_tls_hint') }}</span>
        </span>
        <Switch :model-value="!form.verify_tls" :aria-label="t('gv.proxmox.ignore_tls')" aria-describedby="proxmox-tls-hint" @update:model-value="(v: boolean) => (form.verify_tls = !v)" />
      </label>

      <div class="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <Button type="submit" variant="primary" :loading="saving" :disabled="!canSave" data-test="proxmox-save">{{ t('gv.proxmox.save') }}</Button>
        <Button :loading="syncing" :disabled="!canSync" :title="canSync ? undefined : t('gv.proxmox.sync_needs_save')" data-test="proxmox-sync" @click="sync">
          <RefreshCw v-if="!syncing" aria-hidden="true" />{{ t('gv.proxmox.sync') }}
        </Button>
        <Button v-if="configured" variant="danger-ghost" class="ml-auto" @click="disconnect"><Trash2 aria-hidden="true" />{{ t('gv.proxmox.disconnect') }}</Button>
      </div>
    </form>

    <ProxmoxReport v-if="report && stored?.enabled" :report="report" />

    <p class="flex items-start gap-2 text-xs leading-relaxed text-fg-subtle">
      <Server class="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />{{ t('gv.proxmox.read_only_note') }}
    </p>
  </SettingsSection>
</template>
