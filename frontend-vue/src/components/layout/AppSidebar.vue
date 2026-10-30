<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { NAV_ITEMS, lineInk, lineVar } from './navigation';
import NavPreferences from './NavPreferences.vue';
import { t } from '@/i18n';
import { useNetworkStore } from '@/stores/network';
import { useSshSessions } from '@/stores/sshSessions';

const props = defineProps<{ version?: string; build?: string }>();

const route = useRoute();
const store = useNetworkStore();
const ssh = useSshSessions();
const activeId = computed(() => route.meta.navId as string | undefined);
</script>

<template>
  <aside class="hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-chrome md:flex">
    <div class="flex h-14 items-center gap-2 px-5">
      <span class="text-base font-semibold tracking-tight text-fg">{{ t('app.title') }}</span>
      <span v-if="props.version" class="font-mono text-micro text-fg-subtle">v{{ props.version }}</span>
      <span class="ml-auto rounded-sm border border-accent/25 bg-accent/10 px-1.5 py-px text-micro font-semibold text-accent-text">
        {{ t('gv.brand_tag') }}
      </span>
    </div>
    <!-- A test build says so, with its commit, so it is never mistaken for the release -->
    <p v-if="props.build" class="mx-5 -mt-2 mb-1 truncate rounded-sm border border-warn/30 bg-warn/10 px-1.5 py-px font-mono text-micro text-warn-text" :title="t('gv.build.title')">
      {{ t('gv.build.label', { build: props.build }) }}
    </p>

    <!-- The pages as stops on one route: each has its own line sign, the current stop is filled, a hairline joins the stops -->
    <nav :aria-label="t('sidebar.navigation')" class="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
      <RouterLink
        v-for="(item, index) in NAV_ITEMS"
        :key="item.id"
        :to="item.to"
        :aria-current="activeId === item.id ? 'page' : undefined"
        class="group relative flex h-9 items-center gap-3 rounded-md px-2 text-sm font-medium transition-colors"
        :class="activeId === item.id ? 'bg-raised font-semibold text-fg' : 'text-fg-muted hover:bg-control-hover hover:text-fg'"
      >
        <span
          v-if="index < NAV_ITEMS.length - 1"
          class="absolute top-[calc(50%+13px)] left-[calc(0.5rem+12px)] h-3 w-0.5 bg-line-strong"
          aria-hidden="true"
        />
        <span
          class="relative grid size-[26px] shrink-0 place-items-center rounded-[7px] transition-colors"
          :style="
            activeId === item.id
              ? { background: lineVar(item), color: '#0c0f14' }
              : { background: `color-mix(in oklab, ${lineVar(item)} 16%, transparent)`, color: lineInk(item) }
          "
          aria-hidden="true"
        >
          <component :is="item.icon" class="size-[15px]" :stroke-width="activeId === item.id ? 2.4 : 2" />
        </span>
        <span class="flex-1 truncate">{{ t(item.label) }}</span>
        <span
          v-if="item.id === 'dashboard' && store.totalCount > 0"
          class="font-mono text-xs text-fg-subtle tabular"
          :aria-label="`${store.onlineCount} / ${store.totalCount}`"
        >
          {{ store.onlineCount }}/{{ store.totalCount }}
        </span>
        <span
          v-else-if="item.id === 'ssh' && ssh.liveCount > 0"
          class="rounded-sm bg-accent/15 px-1.5 font-mono text-micro text-accent-text"
          :title="t('ssh.sessions.open_in_background', { count: ssh.liveCount })"
        >
          {{ ssh.liveCount }}
          <span class="sr-only">{{ t('ssh.sessions.open_in_background', { count: ssh.liveCount }) }}</span>
        </span>
      </RouterLink>
    </nav>

    <div class="border-t border-line p-3">
      <NavPreferences />
    </div>
  </aside>
</template>
