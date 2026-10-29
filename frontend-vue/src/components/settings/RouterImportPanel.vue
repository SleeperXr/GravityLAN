<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { Download, ShieldCheck, Trash2 } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { RouterImportPreview, RouterImportProvider, RouterNetworkPreview, RouterSource } from '@/types';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * Import from router: ask a router for its networks (read-only SNMP or the UniFi console
 * API), preview them and add only the picked ones. Existing scan subnets only get an empty
 * gateway/VLAN filled in; nothing changes before "Apply". Secrets are sent, never shown.
 */
const emit = defineEmits<{ applied: [] }>();
const { showToast } = useToast();

const SNMP_VERSIONS = ['2c', '3', '1'].map((v) => ({ value: v, label: `v${v}` }));
const AUTH_PROTOCOLS = ['SHA', 'SHA256', 'SHA384', 'SHA512', 'SHA224', 'MD5'].map((p) => ({ value: p, label: p }));
const PRIV_PROTOCOLS = ['AES', 'AES256', 'AES192', 'DES', '3DES'].map((p) => ({ value: p, label: p }));

const sources = ref<RouterSource[]>([]);
const provider = ref<RouterImportProvider>('snmp');
const host = ref('');
const port = ref<string | number>('');
const options = ref<Record<string, string>>({});
const secrets = ref<Record<string, string>>({});
const preview = ref<RouterImportPreview | null>(null);
const selected = ref(new Set<string>());
const busy = ref<'fetch' | 'apply' | null>(null);
const error = ref<string | null>(null);

const importable = (n: RouterNetworkPreview) => n.status === 'new' || n.status === 'update';

function prefill(list: RouterSource[], key: RouterImportProvider) {
  const saved = list.find((s) => s.provider === key);
  host.value = saved?.host ?? '';
  port.value = saved?.port != null ? String(saved.port) : '';
  options.value = Object.fromEntries(Object.entries(saved?.options ?? {}).filter(([, v]) => !!v)) as Record<string, string>;
  secrets.value = {};
}

async function loadSources(): Promise<RouterSource[]> {
  try {
    const list = await api.getRouterSources();
    sources.value = Array.isArray(list) ? list : [];
  } catch {
    sources.value = [];
  }
  return sources.value;
}

onMounted(async () => {
  const list = await loadSources();
  if (list[0]) {
    provider.value = list[0].provider;
    prefill(list, list[0].provider);
  }
});

const saved = computed(() => sources.value.find((s) => s.provider === provider.value));
const sameRouter = computed(() => !!saved.value && saved.value.host.trim().toLowerCase() === host.value.trim().toLowerCase());
const isStored = (field: string) => sameRouter.value && !!saved.value?.stored_secrets.includes(field);
const snmpVersion = computed(() => options.value.version || '2c');

function switchProvider(key: RouterImportProvider) {
  provider.value = key;
  prefill(sources.value, key);
  preview.value = null;
  error.value = null;
}

async function fetchNetworks(extra: Record<string, string> = {}) {
  if (!host.value.trim()) return;
  busy.value = 'fetch';
  error.value = null;
  const merged = { ...options.value, ...extra };
  const filled = Object.fromEntries(Object.entries(secrets.value).filter(([, v]) => !!v));
  try {
    const result = await api.previewRouterImport({
      provider: provider.value,
      host: host.value.trim(),
      port: String(port.value).trim() ? Number(port.value) : null,
      options: merged,
      secrets: filled,
    });
    options.value = merged;
    preview.value = result;
    selected.value = new Set(result.networks.filter(importable).map((n) => n.cidr));
    if (result.status === 'ok') {
      secrets.value = {};
      await loadSources();
    }
  } catch (err) {
    preview.value = null;
    error.value = `${t('router_import.failed')} ${(err as Error).message}`;
  } finally {
    busy.value = null;
  }
}

function toggle(cidr: string, on: boolean) {
  const next = new Set(selected.value);
  if (on) next.add(cidr);
  else next.delete(cidr);
  selected.value = next;
}

const picked = computed(() => (preview.value?.status === 'ok' ? preview.value.networks.filter((n) => importable(n) && selected.value.has(n.cidr)) : []));

async function apply() {
  if (picked.value.length === 0) return;
  busy.value = 'apply';
  try {
    const result = await api.applyRouterImport(picked.value.map(({ cidr, name, gateway_ip, vlan_id }) => ({ cidr, name, gateway_ip, vlan_id })));
    showToast('success', t('notifications.saved'), t('router_import.applied', { added: result.added.length, updated: result.updated.length }));
    preview.value = null;
    emit('applied');
  } catch (err) {
    showToast('error', t('common.error'), `${t('router_import.apply_failed')} ${(err as Error).message}`);
  } finally {
    busy.value = null;
  }
}

async function forget() {
  try {
    await api.deleteRouterSource(provider.value);
    showToast('success', t('notifications.saved'), t('router_import.forgotten'));
    prefill(await loadSources(), provider.value);
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  }
}

function statusLabel(net: RouterNetworkPreview): string {
  if (net.status === 'update') {
    const fields = net.fills.map((f) => (f === 'gateway_ip' ? t('subnet_gateway.gateway') : t('subnet_gateway.vlan'))).join(', ');
    return t('router_import.status_update', { fields, name: net.existing_name ?? '' });
  }
  if (net.status === 'exists') return t('router_import.status_exists', { name: net.existing_name ?? '' });
  return t(`router_import.status_${net.status}`);
}
const statusTone = (net: RouterNetworkPreview) => (net.status === 'new' ? 'accent' : net.status === 'update' ? 'info' : 'neutral');
</script>

<template>
  <!-- Opens inside the subnets card: a rule on the left marks it as part of the row above, no box in a box -->
  <div class="space-y-4 border-l-2 border-line pl-4">
    <form class="space-y-4" :aria-label="t('router_import.title')" @submit.prevent="fetchNetworks()">
      <div class="grid gap-3 sm:grid-cols-[12rem_1fr_6rem]">
        <Field v-slot="{ id }" :label="t('router_import.provider')">
          <Select :id="id" :model-value="provider" :options="[{ value: 'snmp', label: t('router_import.provider_snmp') }, { value: 'unifi', label: t('router_import.provider_unifi') }]" @update:model-value="(v) => switchProvider(v as RouterImportProvider)" />
        </Field>
        <Field v-slot="{ id, describedBy }" :label="t('router_import.host')" :hint="t('router_import.host_hint')">
          <Input :id="id" v-model="host" mono placeholder="192.168.1.1" :aria-describedby="describedBy" />
        </Field>
        <Field v-slot="{ id }" :label="t('router_import.port')">
          <Input :id="id" v-model="port" mono type="number" min="1" max="65535" :placeholder="provider === 'snmp' ? '161' : '443'" />
        </Field>
      </div>

      <template v-if="provider === 'snmp'">
        <div class="grid gap-3 sm:grid-cols-[6rem_1fr_1fr]">
          <Field v-slot="{ id }" :label="t('router_import.snmp_version')">
            <Select :id="id" :model-value="snmpVersion" :options="SNMP_VERSIONS" @update:model-value="(v) => (options.version = String(v))" />
          </Field>
          <template v-if="snmpVersion === '3'">
            <Field v-slot="{ id }" :label="t('router_import.v3_user')"><Input :id="id" v-model="options.username" autocomplete="off" /></Field>
            <Field v-slot="{ id }" :label="t('router_import.auth_protocol')">
              <Select :id="id" :model-value="options.auth_protocol || 'SHA'" :options="AUTH_PROTOCOLS" @update:model-value="(v) => (options.auth_protocol = String(v))" />
            </Field>
            <Field v-slot="{ id }" :label="t('router_import.auth_key')"><Input :id="id" v-model="secrets.auth_key" type="password" autocomplete="off" :placeholder="isStored('auth_key') ? t('router_import.secret_stored') : ''" /></Field>
            <Field v-slot="{ id }" :label="t('router_import.priv_protocol')">
              <Select :id="id" :model-value="options.priv_protocol || 'AES'" :options="PRIV_PROTOCOLS" @update:model-value="(v) => (options.priv_protocol = String(v))" />
            </Field>
            <Field v-slot="{ id }" :label="t('router_import.priv_key')"><Input :id="id" v-model="secrets.priv_key" type="password" autocomplete="off" :placeholder="isStored('priv_key') ? t('router_import.secret_stored') : ''" /></Field>
          </template>
          <div v-else class="sm:col-span-2">
            <Field v-slot="{ id }" :label="t('router_import.community')"><Input :id="id" v-model="secrets.community" type="password" autocomplete="off" :placeholder="isStored('community') ? t('router_import.secret_stored') : ''" /></Field>
          </div>
        </div>
        <p class="max-w-prose text-xs leading-relaxed text-fg-subtle">{{ t('router_import.snmp_hint') }}</p>
      </template>
      <template v-else>
        <div class="grid gap-3 sm:grid-cols-[1fr_8rem]">
          <Field v-slot="{ id }" :label="t('router_import.api_key')"><Input :id="id" v-model="secrets.api_key" type="password" autocomplete="off" :placeholder="isStored('api_key') ? t('router_import.secret_stored') : ''" /></Field>
          <Field v-slot="{ id }" :label="t('router_import.site')"><Input :id="id" v-model="options.site" placeholder="default" /></Field>
          <div class="sm:col-span-2">
            <Field v-slot="{ id }" :label="t('router_import.fingerprint')"><Input :id="id" v-model="options.fingerprint" mono :placeholder="t('router_import.fingerprint_placeholder')" /></Field>
          </div>
        </div>
        <p class="max-w-prose text-xs leading-relaxed text-fg-subtle">{{ t('router_import.unifi_hint') }}</p>
      </template>

      <div class="flex flex-wrap gap-2">
        <Button type="submit" :loading="busy === 'fetch'" :disabled="!host.trim() || busy !== null"><Download v-if="busy !== 'fetch'" aria-hidden="true" />{{ busy === 'fetch' ? t('router_import.fetching') : t('router_import.fetch') }}</Button>
        <Button v-if="saved" variant="danger-ghost" @click="forget"><Trash2 aria-hidden="true" />{{ t('router_import.forget') }}</Button>
      </div>
    </form>

    <p v-if="error" role="alert" class="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger-text">{{ error }}</p>

    <div v-if="preview?.status === 'confirm_certificate'" role="alert" class="space-y-2 rounded-md border border-warn/40 bg-warn/[0.07] p-3">
      <p class="text-sm font-medium text-fg">{{ t('router_import.cert_title') }}</p>
      <p class="text-xs text-fg-muted">{{ t(preview.reason === 'certificate_mismatch' ? 'router_import.cert_mismatch' : 'router_import.cert_untrusted') }}</p>
      <code class="block rounded-sm bg-sunken px-2 py-1.5 font-mono text-xs break-all text-fg">{{ preview.fingerprint }}</code>
      <Button size="sm" :disabled="busy !== null" @click="fetchNetworks({ fingerprint: preview.fingerprint ?? '' })"><ShieldCheck aria-hidden="true" />{{ t('router_import.cert_trust') }}</Button>
    </div>

    <div v-if="preview?.status === 'ok'" class="space-y-3">
      <p class="text-sm font-medium text-fg">{{ t('router_import.preview_title', { host: preview.host, count: preview.networks.length }) }}</p>
      <p v-if="preview.networks.length === 0" class="text-sm text-fg-subtle">{{ t('router_import.preview_empty') }}</p>
      <template v-else>
        <ul class="divide-y divide-line border-y border-line" :aria-label="t('router_import.preview_list')">
          <li v-for="net in preview.networks" :key="net.cidr" class="flex flex-wrap items-center gap-3 py-2.5" :class="!importable(net) && 'opacity-60'">
            <label class="flex min-w-0 flex-1 items-start gap-3">
              <input
                type="checkbox"
                class="mt-1 size-4 accent-[var(--gl-accent)]"
                :checked="importable(net) && selected.has(net.cidr)"
                :disabled="!importable(net)"
                :aria-label="t('router_import.select_label', { cidr: net.cidr })"
                @change="toggle(net.cidr, ($event.target as HTMLInputElement).checked)"
              />
              <span class="min-w-0">
                <span class="block text-sm text-fg"><code class="font-mono">{{ net.cidr }}</code><span v-if="net.name"> · {{ net.name }}</span></span>
                <span class="block text-xs text-fg-subtle">{{ [net.gateway_ip && `${t('subnet_gateway.gateway')} ${net.gateway_ip}`, net.vlan_id != null && `VLAN ${net.vlan_id}`, net.interface].filter(Boolean).join(' · ') }}</span>
              </span>
            </label>
            <Badge :tone="statusTone(net)">{{ statusLabel(net) }}</Badge>
          </li>
        </ul>
        <div class="flex flex-wrap items-center gap-3">
          <Button variant="primary" :loading="busy === 'apply'" :disabled="picked.length === 0 || busy !== null" @click="apply">{{ t('router_import.apply', { count: picked.length }) }}</Button>
          <p class="text-xs text-fg-subtle">{{ t('router_import.apply_hint') }}</p>
        </div>
      </template>
    </div>
  </div>
</template>
