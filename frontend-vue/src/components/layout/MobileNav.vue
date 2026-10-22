<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Menu } from 'lucide-vue-next';
import { NAV_ITEMS, TAB_IDS, lineInk, lineVar } from './navigation';
import NavPreferences from './NavPreferences.vue';
import Dialog from '@/components/ui/Dialog.vue';
import { t } from '@/i18n';
import { useSshSessions } from '@/stores/sshSessions';

/** Phone chrome: bottom tab bar (thumb reach) and a "More" sheet with the remaining pages. */
const route = useRoute();
const menuOpen = ref(false);
const ssh = useSshSessions();

const tabs = computed(() => NAV_ITEMS.filter((item) => (TAB_IDS as readonly string[]).includes(item.id)));
const activeId = computed(() => (route.meta.navId as string | undefined) ?? 'dashboard');
const moreActive = computed(() => !(TAB_IDS as readonly string[]).includes(activeId.value));

watch(() => route.fullPath, () => (menuOpen.value = false));
</script>

<template>
  <nav
    :aria-label="t('sidebar.navigation')"
    class="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-chrome/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
  >
    <RouterLink
      v-for="item in tabs"
      :key="item.id"
      :to="item.to"
      :aria-current="activeId === item.id ? 'page' : undefined"
      class="relative flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors"
      :class="activeId === item.id ? 'text-fg' : 'text-fg-subtle'"
    >
      <span v-if="activeId === item.id" class="absolute inset-x-4 top-0 h-[3px] rounded-b-full" :style="{ background: lineVar(item) }" aria-hidden="true" />
      <component :is="item.icon" class="size-5" :style="activeId === item.id ? { color: lineInk(item) } : undefined" aria-hidden="true" />
      <span class="max-w-full truncate px-1">{{ t(item.label) }}</span>
    </RouterLink>
    <button
      type="button"
      class="relative flex min-h-14 flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium"
      :class="moreActive ? 'text-accent-text' : 'text-fg-subtle'"
      :aria-expanded="menuOpen"
      @click="menuOpen = true"
    >
      <Menu class="size-5" aria-hidden="true" />
      <span>{{ t('gv.more') }}</span>
      <span v-if="ssh.liveCount > 0" class="absolute top-2 right-[calc(50%-18px)] size-2 rounded-full bg-accent" aria-hidden="true" />
    </button>
  </nav>

  <Dialog v-model:open="menuOpen" :title="t('sidebar.navigation')" size="sm">
    <nav :aria-label="t('sidebar.navigation')" class="-mx-2 grid gap-0.5">
      <RouterLink
        v-for="item in NAV_ITEMS"
        :key="item.id"
        :to="item.to"
        :aria-current="activeId === item.id ? 'page' : undefined"
        class="flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium"
        :class="activeId === item.id ? 'bg-raised text-fg' : 'text-fg-muted hover:bg-control-hover hover:text-fg'"
      >
        <span
          class="grid size-7 shrink-0 place-items-center rounded-[7px]"
          :style="
            activeId === item.id
              ? { background: lineVar(item), color: '#0c0f14' }
              : { background: `color-mix(in oklab, ${lineVar(item)} 16%, transparent)`, color: lineInk(item) }
          "
          aria-hidden="true"
        >
          <component :is="item.icon" class="size-4" />
        </span>
        <span class="flex-1">{{ t(item.label) }}</span>
        <span v-if="item.id === 'ssh' && ssh.liveCount > 0" class="rounded-sm bg-accent/15 px-1.5 font-mono text-xs text-accent-text">
          {{ ssh.liveCount }}
        </span>
      </RouterLink>
    </nav>
    <div class="mt-4 border-t border-line pt-4">
      <NavPreferences />
    </div>
  </Dialog>
</template>
