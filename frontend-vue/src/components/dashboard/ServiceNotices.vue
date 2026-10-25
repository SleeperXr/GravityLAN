<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMediaQuery } from '@vueuse/core';
import { ArrowRight, CheckCircle2 } from 'lucide-vue-next';
import LineBullet from '@/components/common/LineBullet.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import type { Notice } from '@/lib/notices';
import { lineLabelFor, networkColor } from '@/lib/networks';
import { t } from '@/i18n';

/** Service notices: everything that needs the operator, most urgent first (see buildNotices). */
const props = defineProps<{ notices: Notice[] }>();
const emit = defineEmits<{ open: [notice: Notice] }>();

/** Below xl the list sits in the page flow (no inner scroll box), so a long list is cut short instead. */
const COLLAPSED_COUNT = 5;
const besideMap = useMediaQuery('(min-width: 1280px)');
const expanded = ref(false);
const collapsible = computed(() => !besideMap.value && props.notices.length > COLLAPSED_COUNT);
const shown = computed(() => (collapsible.value && !expanded.value ? props.notices.slice(0, COLLAPSED_COUNT) : props.notices));
</script>

<template>
  <section class="gl-card flex min-h-0 flex-col" aria-labelledby="notices-title">
    <header class="flex items-baseline justify-between border-b border-line px-4 py-3">
      <h2 id="notices-title" class="text-sm font-bold text-fg">{{ t('gv.notices.title') }}</h2>
      <span class="font-mono text-xs text-fg-subtle tabular">{{ notices.length }}</span>
    </header>
    <div v-if="notices.length === 0" class="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <CheckCircle2 class="size-6 text-accent-text" aria-hidden="true" />
      <p class="text-sm font-semibold text-fg">{{ t('gv.notices.all_clear') }}</p>
      <p class="text-xs text-fg-subtle">{{ t('gv.notices.all_clear_hint') }}</p>
    </div>
    <ul v-else class="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
      <li v-for="n in shown" :key="n.key">
        <button type="button" class="group flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-raised" @click="emit('open', n)">
          <!-- The badge of the network orbit the device belongs to; fleet-wide notices get a neutral sign -->
          <LineBullet
            v-if="n.device"
            :color="networkColor(n.device.subnet_id, n.device.ip)"
            :label="lineLabelFor(n.device.subnet_id)"
            size="sm"
            class="mt-0.5"
          />
          <LineBullet v-else color="var(--gl-fg-muted)" label="A" size="sm" class="mt-0.5" />
          <span class="min-w-0 flex-1">
            <span class="block text-sm leading-5 font-bold" :class="n.tone === 'danger' ? 'text-danger-text' : n.tone === 'warn' ? 'text-warn-text' : 'text-fg'">
              {{ n.title }}
            </span>
            <span class="mt-0.5 block truncate font-mono text-[11px] text-fg-subtle">{{ n.detail }}</span>
            <span v-if="n.since" class="mt-0.5 block text-[11px] text-fg-subtle"><RelativeTime :date="n.since" /></span>
          </span>
          <ArrowRight class="mt-1 size-4 shrink-0 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
        </button>
      </li>
    </ul>
    <button
      v-if="collapsible"
      type="button"
      class="min-h-11 border-t border-line px-4 text-left text-sm font-semibold text-fg-muted transition-colors hover:bg-raised hover:text-fg"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? t('gv.notices.show_fewer') : t('gv.notices.show_all', { count: notices.length }) }}
    </button>
  </section>
</template>
