<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import {
  Bell,
  CheckCircle2,
  Clock,
  KeyRound,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  XCircle,
} from 'lucide-vue-next';
import { api } from '@/api/client';
import type { NotificationOutboxResponse, WebhookSubscriptionResponse } from '@/types';
import SettingsSection from './SettingsSection.vue';
import Button from '@/components/ui/Button.vue';
import Input from '@/components/ui/Input.vue';
import Badge from '@/components/ui/Badge.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { t } from '@/i18n';

const { showToast } = useToast();
const { confirm } = useConfirm();

const webhooks = ref<WebhookSubscriptionResponse[]>([]);
const outbox = ref<NotificationOutboxResponse[]>([]);
const loading = ref(false);
const adding = ref(false);
const testingId = ref<number | null>(null);
const retryingId = ref<number | null>(null);

// Form state
const serviceType = ref<'webhook' | 'ntfy' | 'gotify'>('webhook');
const newName = ref('');
const newUrl = ref('');
const newToken = ref('');
const selectedEvents = ref<string[]>(['device.offline', 'device.online', 'new_device']);

const availableEvents = computed(() => [
  { id: 'device.offline', label: t('gv.webhooks.event_device_offline') },
  { id: 'device.online', label: t('gv.webhooks.event_device_online') },
  { id: 'new_device', label: t('gv.webhooks.event_new_device') },
  { id: 'device.ip_changed', label: t('gv.webhooks.event_ip_changed') },
  { id: 'scan.complete', label: t('gv.webhooks.event_scan_complete') },
]);

const urlPlaceholder = computed(() => {
  if (serviceType.value === 'ntfy') return 'https://ntfy.sh/topic-name';
  if (serviceType.value === 'gotify') return 'https://gotify.example.com';
  return 'https://example.com/api/webhook';
});

const tokenPlaceholder = computed(() => {
  if (serviceType.value === 'ntfy') return t('gv.webhooks.token_ntfy');
  if (serviceType.value === 'gotify') return t('gv.webhooks.token_gotify');
  return t('gv.webhooks.token_webhook');
});

async function load() {
  loading.value = true;
  try {
    const [subs, outboxItems] = await Promise.all([
      api.getWebhooks(),
      api.getOutbox(20),
    ]);
    webhooks.value = subs;
    outbox.value = outboxItems;
  } catch {
    // Keep current state on transient failure
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function toggleEvent(id: string) {
  if (selectedEvents.value.includes(id)) {
    selectedEvents.value = selectedEvents.value.filter((e) => e !== id);
  } else {
    selectedEvents.value.push(id);
  }
}

async function addSubscription() {
  const url = newUrl.value.trim();
  if (!url || selectedEvents.value.length === 0) return;

  adding.value = true;
  try {
    await api.createWebhook({
      name: newName.value.trim() || undefined,
      url,
      service_type: serviceType.value,
      token: newToken.value.trim() || undefined,
      events: selectedEvents.value,
    });
    showToast('success', t('common.success'), t('gv.webhooks.created_success'));
    newName.value = '';
    newUrl.value = '';
    newToken.value = '';
    await load();
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    adding.value = false;
  }
}

async function removeSubscription(sub: WebhookSubscriptionResponse) {
  const ok = await confirm({
    title: t('gv.webhooks.delete_title', { name: sub.name || sub.url }),
    message: t('gv.webhooks.delete_confirm'),
    danger: true,
  });
  if (!ok) return;

  try {
    await api.deleteWebhook(sub.id);
    showToast('success', t('common.success'), t('gv.webhooks.deleted_success'));
    await load();
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  }
}

async function sendTest(sub: WebhookSubscriptionResponse) {
  testingId.value = sub.id;
  try {
    await api.testWebhook('test.event', {
      status: 'testing',
      destination: sub.name || sub.url,
      subscription_id: sub.id,
    });
    showToast('info', t('gv.webhooks.test_sent_title'), t('gv.webhooks.test_sent_desc'));
    setTimeout(load, 1500);
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    testingId.value = null;
  }
}

async function retryOutboxEntry(entry: NotificationOutboxResponse) {
  retryingId.value = entry.id;
  try {
    await api.retryOutbox(entry.id);
    showToast('success', t('common.success'), t('gv.webhooks.retry_success'));
    await load();
  } catch (err) {
    showToast('error', t('common.error'), (err as Error).message);
  } finally {
    retryingId.value = null;
  }
}

function serviceTone(type: string): 'neutral' | 'accent' | 'info' {
  if (type === 'ntfy') return 'accent';
  if (type === 'gotify') return 'info';
  return 'neutral';
}
</script>

<template>
  <SettingsSection id="notifications" :title="t('gv.webhooks.section')" :description="t('gv.webhooks.section_desc')">
    <!-- Presets / Add Destination Form -->
    <div class="rounded-lg border border-line bg-raised/40 p-4 space-y-4">
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold text-fg-muted uppercase tracking-wider">{{ t('gv.webhooks.preset') }}:</span>
        <div class="inline-flex rounded-md border border-line bg-sunken p-0.5">
          <button
            type="button"
            class="px-2.5 py-1 text-xs font-medium rounded transition-colors"
            :class="serviceType === 'webhook' ? 'bg-raised text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
            @click="serviceType = 'webhook'"
          >
            Webhook
          </button>
          <button
            type="button"
            class="px-2.5 py-1 text-xs font-medium rounded transition-colors"
            :class="serviceType === 'ntfy' ? 'bg-raised text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
            @click="serviceType = 'ntfy'"
          >
            ntfy
          </button>
          <button
            type="button"
            class="px-2.5 py-1 text-xs font-medium rounded transition-colors"
            :class="serviceType === 'gotify' ? 'bg-raised text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
            @click="serviceType = 'gotify'"
          >
            Gotify
          </button>
        </div>
      </div>

      <form class="space-y-3" @submit.prevent="addSubscription">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Input
            v-model="newName"
            :placeholder="t('gv.webhooks.name_placeholder')"
            :aria-label="t('gv.webhooks.name')"
            :disabled="adding"
          />
          <Input
            v-model="newToken"
            type="password"
            :placeholder="tokenPlaceholder"
            :aria-label="tokenPlaceholder"
            :disabled="adding"
          />
        </div>

        <Input
          v-model="newUrl"
          :placeholder="urlPlaceholder"
          :aria-label="t('gv.webhooks.url')"
          :disabled="adding"
          required
        />

        <div class="space-y-1.5 pt-1">
          <span class="text-xs font-medium text-fg-muted">{{ t('gv.webhooks.events') }}:</span>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="ev in availableEvents"
              :key="ev.id"
              type="button"
              class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors"
              :class="
                selectedEvents.includes(ev.id)
                  ? 'border-accent/40 bg-accent/15 text-accent-text font-medium'
                  : 'border-line bg-raised text-fg-muted hover:text-fg'
              "
              @click="toggleEvent(ev.id)"
            >
              <CheckCircle2 v-if="selectedEvents.includes(ev.id)" class="size-3.5" aria-hidden="true" />
              {{ ev.label }}
            </button>
          </div>
        </div>

        <div class="flex justify-end pt-1">
          <Button type="submit" :loading="adding" :disabled="!newUrl.trim() || selectedEvents.length === 0">
            <Plus v-if="!adding" aria-hidden="true" />
            {{ t('gv.webhooks.btn_add') }}
          </Button>
        </div>
      </form>
    </div>

    <!-- Active destinations list -->
    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-semibold text-fg-muted uppercase tracking-wider">
          {{ t('gv.webhooks.section') }} ({{ webhooks.length }})
        </h3>
        <Button size="icon-sm" variant="ghost" :loading="loading" @click="load">
          <RefreshCw aria-hidden="true" />
        </Button>
      </div>

      <EmptyState v-if="webhooks.length === 0" compact :icon="Bell" :title="t('gv.webhooks.empty_title')" :description="t('gv.webhooks.empty_desc')" />

      <ul v-else class="divide-y divide-line border-y border-line">
        <li v-for="sub in webhooks" :key="sub.id" class="flex items-center justify-between gap-3 py-3">
          <div class="min-w-0 flex-1 space-y-1">
            <div class="flex items-center gap-2">
              <Badge :tone="serviceTone(sub.service_type)" class="uppercase">{{ sub.service_type }}</Badge>
              <span v-if="sub.name" class="text-sm font-medium text-fg truncate">{{ sub.name }}</span>
              <span v-if="sub.has_token" class="inline-flex items-center text-accent-text" title="Token configured">
                <KeyRound class="size-3.5" aria-hidden="true" />
              </span>
            </div>
            <p class="font-mono text-xs text-fg-subtle truncate max-w-xl">{{ sub.url }}</p>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="e in sub.events"
                :key="e"
                class="rounded bg-sunken px-1.5 py-0.5 text-micro font-mono text-fg-muted"
              >
                {{ e }}
              </span>
            </div>
          </div>

          <div class="flex items-center gap-1.5 shrink-0">
            <Button
              size="sm"
              variant="secondary"
              :loading="testingId === sub.id"
              :disabled="testingId !== null"
              @click="sendTest(sub)"
            >
              <Send v-if="testingId !== sub.id" aria-hidden="true" />
              {{ t('gv.webhooks.btn_test') }}
            </Button>
            <Button
              size="icon-sm"
              variant="danger-ghost"
              :aria-label="t('gv.webhooks.btn_delete')"
              @click="removeSubscription(sub)"
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </div>
        </li>
      </ul>
    </div>

    <!-- Notification Outbox Status -->
    <div class="space-y-3 pt-3">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-semibold text-fg-muted uppercase tracking-wider flex items-center gap-2">
          <Clock class="size-3.5" aria-hidden="true" />
          {{ t('gv.webhooks.outbox_title') }}
        </h3>
      </div>

      <div v-if="outbox.length === 0" class="text-xs text-fg-muted italic py-2">
        {{ t('gv.webhooks.outbox_empty') }}
      </div>

      <div v-else class="rounded-md border border-line bg-raised/20 overflow-hidden">
        <div class="divide-y divide-line text-xs">
          <div
            v-for="item in outbox"
            :key="item.id"
            class="flex items-center justify-between gap-3 p-2.5"
          >
            <div class="min-w-0 flex-1 space-y-0.5">
              <div class="flex items-center gap-2">
                <Badge
                  :tone="item.status === 'delivered' ? 'accent' : item.status === 'failed' ? 'danger' : 'warn'"
                >
                  <CheckCircle2 v-if="item.status === 'delivered'" class="size-3" aria-hidden="true" />
                  <XCircle v-else-if="item.status === 'failed'" class="size-3" aria-hidden="true" />
                  <Clock v-else class="size-3" aria-hidden="true" />
                  {{
                    item.status === 'delivered'
                      ? t('gv.webhooks.status_delivered')
                      : item.status === 'failed'
                        ? t('gv.webhooks.status_failed')
                        : t('gv.webhooks.status_pending')
                  }}
                </Badge>
                <code class="font-mono text-fg font-medium">{{ item.event_type }}</code>
                <span class="text-fg-subtle">({{ item.service_type }})</span>
                <span class="text-fg-muted text-micro">
                  {{ t('gv.webhooks.attempts', { count: item.attempts, max: item.max_attempts }) }}
                </span>
              </div>
              <p class="truncate font-mono text-fg-muted text-micro max-w-lg">{{ item.target_url }}</p>
              <p v-if="item.last_error" class="text-danger-text text-micro truncate max-w-xl">
                {{ item.last_error }}
              </p>
            </div>

            <div class="flex items-center gap-2 shrink-0 text-right">
              <span class="text-micro text-fg-subtle">
                <RelativeTime :date="item.created_at" />
              </span>
              <Button
                v-if="item.status === 'failed'"
                size="sm"
                variant="secondary"
                :loading="retryingId === item.id"
                @click="retryOutboxEntry(item)"
              >
                <RefreshCw v-if="retryingId !== item.id" aria-hidden="true" />
                {{ t('gv.webhooks.btn_retry') }}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </SettingsSection>
</template>
