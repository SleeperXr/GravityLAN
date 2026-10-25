<script setup lang="ts">
import { computed } from 'vue';
import { useNow } from '@vueuse/core';
import { ArrowRight, CircleAlert, CircleCheck, TriangleAlert } from 'lucide-vue-next';
import Button from '@/components/ui/Button.vue';
import RelativeTime from '@/components/common/RelativeTime.vue';
import { isStale, summarizeFleet, type Notice } from '@/lib/notices';
import { t } from '@/i18n';

/**
 * One sentence that answers "is everything all right?" above the dashboard: what is disrupted,
 * how many devices are online and how fresh the data is, with a jump to the most urgent notice.
 */
const props = defineProps<{ notices: Notice[]; online: number; total: number; loadedAt: number | null }>();
const emit = defineEmits<{ open: [notice: Notice] }>();

const now = useNow({ interval: 10_000 });
const summary = computed(() => summarizeFleet(props.notices));
const stale = computed(() => isStale(props.loadedAt, now.value.getTime()));

const TONES = {
  danger: { icon: CircleAlert, text: 'text-danger-text', edge: 'border-l-danger' },
  warn: { icon: TriangleAlert, text: 'text-warn-text', edge: 'border-l-warn' },
  ok: { icon: CircleCheck, text: 'text-accent-text', edge: 'border-l-accent' },
} as const;
const tone = computed(() => TONES[summary.value.tone]);
</script>

<template>
  <section
    :aria-label="t('gv.fleet.title')"
    class="gl-card flex flex-wrap items-center gap-x-5 gap-y-2 border-l-[3px] py-3 pr-3 pl-4"
    :class="tone.edge"
  >
    <span class="flex min-w-0 flex-[1_1_18rem] items-center gap-2.5">
      <component :is="tone.icon" class="size-5 shrink-0" :class="tone.text" aria-hidden="true" />
      <!-- Only the sentence is live: the ticking timestamp would make screen readers chatter -->
      <span role="status" aria-live="polite" class="min-w-0 text-[15px] leading-5 font-bold" :class="tone.text">
        {{ summary.headline }}
        <span v-if="summary.tone === 'ok' && summary.infoCount > 0" class="font-medium text-fg-muted">
          · {{ t('gv.fleet.info', { count: summary.infoCount }) }}
        </span>
      </span>
    </span>
    <span class="flex flex-wrap items-center gap-x-2 font-mono text-xs text-fg-muted tabular">
      <span>{{ t('gv.fleet.online', { online, total }) }}</span>
      <span aria-hidden="true">·</span>
      <span :class="stale && 'font-semibold text-warn-text'">
        {{ t('gv.fleet.as_of') }} <RelativeTime :date="loadedAt" />
        <!-- Its own live region: announced when the data goes stale, silent while the time ticks -->
        <span aria-live="polite"><template v-if="stale">· {{ t('gv.fleet.stale') }}</template></span>
      </span>
    </span>
    <Button v-if="summary.top" @click="emit('open', summary.top)">
      {{ t('gv.fleet.to_problem') }}<ArrowRight aria-hidden="true" />
    </Button>
  </section>
</template>
