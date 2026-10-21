<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { ExternalLink } from 'lucide-vue-next';
import EmptyState from '@/components/ui/EmptyState.vue';
import { NAV_ITEMS } from '@/components/layout/navigation';
import { t } from '@/i18n';

/** Placeholder for pages that are not ported yet: a direct link to the same page in the React UI. */
const route = useRoute();
const item = computed(() => NAV_ITEMS.find((nav) => nav.id === route.meta.navId));
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-10 md:px-8">
    <div class="gl-card">
      <EmptyState
        :icon="item?.icon"
        :title="t('gv.legacy.only_title', { page: item ? t(item.label) : '' })"
        :description="t('gv.legacy.only_desc')"
      >
        <a
          :href="item?.to ?? '/'"
          class="inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3.5 text-sm font-semibold text-accent-fg hover:bg-accent-hover"
        >
          {{ t('gv.legacy.open') }}
          <ExternalLink class="size-4" aria-hidden="true" />
        </a>
      </EmptyState>
    </div>
  </div>
</template>
