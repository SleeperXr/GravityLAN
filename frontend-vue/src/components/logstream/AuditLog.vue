<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { RefreshCw, ScrollText, Search } from 'lucide-vue-next';
import { api } from '@/api/client';
import Badge from '@/components/ui/Badge.vue';
import Button from '@/components/ui/Button.vue';
import EmptyState from '@/components/ui/EmptyState.vue';
import Select from '@/components/ui/Select.vue';
import { formatDateTime, t } from '@/i18n';
import { parseDate } from '@/lib/relativeTime';
import { AUDIT_CATEGORIES, RESULT_TONE, actionLabel, actorLabel, type AuditCategory, type AuditEvent, type AuditResult } from './auditModel';

/**
 * Who did what, when, from where: remote access, credentials, backups and logins (GET /api/audit).
 * Newest first, 100 at a time; secrets and terminal input are never part of it.
 */
const category = ref<AuditCategory>('all');
const result = ref<AuditResult | ''>('');
const search = ref('');
const items = ref<AuditEvent[]>([]);
const hasMore = ref(false);
const retentionDays = ref(90);
const loading = ref(false);
const error = ref<string | null>(null);
let searchTimer: number | undefined;
let generation = 0;

const categories = Object.keys(AUDIT_CATEGORIES) as AuditCategory[];
const resultOptions = computed(() => [
  { value: '' as const, label: t('gv.audit.result_all') },
  ...(['ok', 'failed', 'denied'] as const).map((r) => ({ value: r, label: t(`gv.audit.result.${r}`) })),
]);

async function load(more = false) {
  const run = ++generation;
  loading.value = true;
  try {
    const page = await api.getAuditEvents({
      action: AUDIT_CATEGORIES[category.value].join(',') || undefined,
      result: result.value || undefined,
      q: search.value.trim() || undefined,
      before_id: more ? items.value.at(-1)?.id : undefined,
    });
    if (run !== generation) return;
    items.value = more ? [...items.value, ...page.items] : page.items;
    hasMore.value = page.has_more;
    retentionDays.value = page.retention_days;
    error.value = null;
  } catch (err) {
    if (run === generation) error.value = (err as Error).message;
  } finally {
    if (run === generation) loading.value = false;
  }
}

watch([category, result], () => void load(), { immediate: true });
watch(search, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => void load(), 300);
});
onBeforeUnmount(() => window.clearTimeout(searchTimer));

const when = (e: AuditEvent) => {
  const date = parseDate(e.created_at);
  return date ? formatDateTime(date, { dateStyle: 'short', timeStyle: 'medium' }) : e.created_at;
};
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4 pt-4">
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex max-w-full overflow-x-auto rounded-md border border-line bg-sunken p-0.5 [scrollbar-width:none]" role="group" :aria-label="t('gv.audit.category_label')">
        <button
          v-for="c in categories"
          :key="c"
          type="button"
          class="inline-flex h-8 shrink-0 items-center rounded-[7px] px-3 text-xs font-semibold transition-colors"
          :class="category === c ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="category === c"
          @click="category = c"
        >
          {{ t(`gv.audit.category.${c}`) }}
        </button>
      </div>
      <Select v-model="result" :options="resultOptions" class="w-40" :aria-label="t('gv.audit.result_label')" />
      <label class="relative min-w-0 flex-1 sm:max-w-xs">
        <span class="sr-only">{{ t('gv.audit.search') }}</span>
        <Search class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
        <input v-model="search" type="search" :placeholder="t('gv.audit.search')" class="h-9 w-full rounded-md border border-line bg-surface pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:outline-none" />
      </label>
      <Button size="icon" variant="ghost" class="ml-auto" :aria-label="t('gv.audit.refresh')" :title="t('gv.audit.refresh')" :disabled="loading" @click="load()">
        <RefreshCw :class="loading && 'animate-spin'" aria-hidden="true" />
      </Button>
    </div>

    <section class="gl-card min-h-0 flex-1 overflow-auto" :aria-label="t('gv.audit.title')" :aria-busy="loading">
      <p v-if="error" class="px-5 py-4 text-sm text-danger-text" role="alert">{{ error }}</p>
      <EmptyState v-else-if="!loading && items.length === 0" :icon="ScrollText" :title="t('gv.audit.empty')" :description="t('gv.audit.empty_hint')" compact />

      <table v-else class="w-full text-left text-sm">
        <thead class="sticky top-0 z-[1] bg-surface">
          <tr class="border-b border-line text-xs font-medium text-fg-subtle">
            <th class="px-4 py-2.5 font-medium whitespace-nowrap">{{ t('gv.audit.col.time') }}</th>
            <th class="px-4 py-2.5 font-medium">{{ t('gv.audit.col.action') }}</th>
            <th class="hidden px-4 py-2.5 font-medium md:table-cell">{{ t('gv.audit.col.target') }}</th>
            <th class="hidden px-4 py-2.5 font-medium lg:table-cell">{{ t('gv.audit.col.who') }}</th>
            <th class="px-4 py-2.5 text-right font-medium">{{ t('gv.audit.col.result') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-for="e in items" :key="e.id" class="align-top hover:bg-raised">
            <td class="px-4 py-2.5 font-mono text-xs whitespace-nowrap text-fg-muted tabular">{{ when(e) }}</td>
            <td class="px-4 py-2.5">
              <p class="font-medium text-fg">{{ actionLabel(e.action) }}</p>
              <!-- On phones the target and the caller move under the action -->
              <p v-if="e.target" class="truncate font-mono text-xs text-fg-muted md:hidden">{{ e.target }}</p>
              <p class="text-xs text-fg-subtle lg:hidden">{{ actorLabel(e.actor) }}<template v-if="e.source_ip"> · {{ e.source_ip }}</template></p>
              <p v-if="e.detail" class="text-xs [overflow-wrap:anywhere] text-fg-subtle md:hidden">{{ e.detail }}</p>
            </td>
            <td class="hidden max-w-[24rem] px-4 py-2.5 md:table-cell">
              <p class="truncate font-mono text-xs text-fg" :title="e.target">{{ e.target || '–' }}</p>
              <p v-if="e.detail" class="text-xs [overflow-wrap:anywhere] text-fg-subtle">{{ e.detail }}</p>
            </td>
            <td class="hidden px-4 py-2.5 lg:table-cell">
              <p class="text-xs text-fg">{{ actorLabel(e.actor) }}</p>
              <p v-if="e.source_ip" class="font-mono text-xs text-fg-subtle">{{ e.source_ip }}</p>
            </td>
            <td class="px-4 py-2.5 text-right">
              <Badge :tone="RESULT_TONE[e.result] ?? 'neutral'">{{ t(`gv.audit.result.${e.result}`) }}</Badge>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="hasMore" class="flex justify-center border-t border-line p-3">
        <Button size="sm" :loading="loading" @click="load(true)">{{ t('gv.audit.more') }}</Button>
      </div>
    </section>

    <p class="text-xs text-fg-subtle">{{ t('gv.audit.retention', { days: retentionDays }) }}</p>
  </div>
</template>
