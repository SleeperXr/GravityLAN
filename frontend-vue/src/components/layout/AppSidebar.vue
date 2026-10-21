<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { NAV_ITEMS } from './navigation';
import NavPreferences from './NavPreferences.vue';
import { t } from '@/i18n';
import { useNetworkStore } from '@/stores/network';
import { useSshSessions } from '@/stores/sshSessions';

const props = defineProps<{ version?: string }>();

const route = useRoute();
const store = useNetworkStore();
const ssh = useSshSessions();
const activeId = computed(() => route.meta.navId as string | undefined);
</script>

<template>
  <aside class="hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-chrome md:flex">
    <div class="flex h-14 items-center gap-2 px-5">
      <span class="text-[15px] font-semibold tracking-tight text-fg">{{ t('app.title') }}</span>
      <span v-if="props.version" class="font-mono text-[11px] text-fg-subtle">v{{ props.version }}</span>
      <span class="ml-auto rounded-sm border border-accent/25 bg-accent/10 px-1.5 py-px text-[10px] font-semibold text-accent-text">
        {{ t('gv.brand_tag') }}
      </span>
    </div>

    <nav :aria-label="t('sidebar.navigation')" class="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
      <RouterLink
        v-for="item in NAV_ITEMS"
        :key="item.id"
        :to="item.to"
        :aria-current="activeId === item.id ? 'page' : undefined"
        class="group relative flex h-9 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors"
        :class="activeId === item.id ? 'bg-raised text-fg' : 'text-fg-muted hover:bg-control-hover hover:text-fg'"
      >
        <span
          v-if="activeId === item.id"
          class="absolute top-2 bottom-2 -left-3 w-0.5 rounded-r-full bg-accent"
          aria-hidden="true"
        />
        <component
          :is="item.icon"
          class="size-[18px] shrink-0"
          :class="activeId === item.id ? 'text-accent-text' : 'text-fg-subtle group-hover:text-fg-muted'"
          aria-hidden="true"
        />
        <span class="flex-1 truncate">{{ t(item.label) }}</span>
        <span
          v-if="item.id === 'dashboard' && store.totalCount > 0"
          class="font-mono text-[11px] text-fg-subtle tabular"
          :aria-label="`${store.onlineCount} / ${store.totalCount}`"
        >
          {{ store.onlineCount }}/{{ store.totalCount }}
        </span>
        <span
          v-else-if="item.id === 'ssh' && ssh.liveCount > 0"
          class="rounded-sm bg-accent/15 px-1.5 font-mono text-[11px] text-accent-text"
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
