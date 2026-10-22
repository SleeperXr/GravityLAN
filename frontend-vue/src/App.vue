<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Loader2, Radar, Square } from 'lucide-vue-next';
import { api, sessionExpired } from '@/api/client';
import { useNetworkStore } from '@/stores/network';
import { useAppearance } from '@/stores/appearance';
import AppSidebar from '@/components/layout/AppSidebar.vue';
import MobileNav from '@/components/layout/MobileNav.vue';
import ToastHost from '@/components/ui/ToastHost.vue';
import ConfirmHost from '@/components/ui/ConfirmHost.vue';
import Button from '@/components/ui/Button.vue';
import LoginView from '@/views/LoginView.vue';
import SetupView from '@/views/SetupView.vue';
import { t } from '@/i18n';

type BootState = 'checking' | 'setup' | 'login' | 'ready';

const store = useNetworkStore();
const appearance = useAppearance();
const route = useRoute();
const state = ref<BootState>('checking');
const version = ref<string>();

const pageTitle = computed(() => (route.meta.titleKey ? t(route.meta.titleKey) : t('app.title')));
watch(pageTitle, (title) => (document.title = `${title} · ${t('app.title')}`), { immediate: true });

async function boot() {
  state.value = 'checking';
  try {
    const setup = await api.getSetupStatus();
    version.value = setup.version;
    if (!setup.is_setup_complete) {
      state.value = 'setup';
      return;
    }
  } catch {
    // Backend unreachable: the login screen at least shows something actionable
  }
  try {
    await api.checkAuth();
  } catch {
    state.value = 'login';
    return;
  }
  sessionExpired.value = false;
  state.value = 'ready';
  store.fetchInventory(true).catch(() => {});
  store.connectScanStream();
  // Custom line colours apply on every page, not only once the network map was opened
  void appearance.load();
}

watch(sessionExpired, (expired) => {
  if (expired && state.value === 'ready') {
    store.disconnectScanStream();
    state.value = 'login';
  }
});

const scanPercent = computed(() => {
  const p = store.scanProgress;
  if (!p?.hosts_total) return null;
  return Math.min(100, Math.round(((p.hosts_scanned ?? 0) / p.hosts_total) * 100));
});

onMounted(boot);
onBeforeUnmount(() => store.disconnectScanStream());
</script>

<template>
  <div v-if="state === 'checking'" class="flex min-h-dvh items-center justify-center gap-2.5 bg-canvas text-sm text-fg-muted" role="status">
    <Loader2 class="size-4 animate-spin text-accent-text" aria-hidden="true" />
    {{ t('app_status.initializing') }}
  </div>

  <SetupView v-else-if="state === 'setup'" @complete="boot" />

  <LoginView v-else-if="state === 'login'" @authenticated="boot" />

  <div v-else class="flex h-dvh overflow-hidden bg-canvas text-fg">
    <a
      href="#main"
      class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[70] focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow-pop"
    >
      {{ t('gv.skip_to_content') }}
    </a>
    <AppSidebar :version="version" />

    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Phone app bar -->
      <header class="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-chrome px-4 pt-[env(safe-area-inset-top)] md:hidden">
        <span class="text-xs font-semibold text-fg-subtle">{{ t('app.title') }}</span>
        <span class="text-fg-subtle" aria-hidden="true">/</span>
        <span class="truncate text-sm font-semibold text-fg">{{ pageTitle }}</span>
      </header>

      <!-- Live scan strip: visible on every page while the scanner runs -->
      <div
        v-if="store.isScanning"
        role="status"
        class="relative flex shrink-0 items-center gap-3 overflow-hidden border-b border-accent/20 bg-accent/[0.07] px-4 py-2 text-xs md:px-8"
      >
        <Radar class="size-4 shrink-0 animate-spin text-accent-text [animation-duration:2.5s]" aria-hidden="true" />
        <span class="font-medium text-fg">{{ t('gv.scan.running') }}</span>
        <span v-if="store.scanProgress?.current_subnet" class="hidden truncate font-mono text-fg-muted sm:inline">
          {{ store.scanProgress.current_subnet }}
        </span>
        <span v-if="store.scanProgress?.hosts_total" class="font-mono text-fg-muted tabular">
          {{ t('gv.scan.progress', { done: store.scanProgress.hosts_scanned ?? 0, total: store.scanProgress.hosts_total }) }}
        </span>
        <Button size="sm" variant="ghost" class="ml-auto h-7" @click="store.stopScan()">
          <Square aria-hidden="true" />
          {{ t('gv.scan.stop') }}
        </Button>
        <div v-if="scanPercent !== null" class="absolute inset-x-0 bottom-0 h-0.5 bg-accent/15" aria-hidden="true">
          <div class="h-full bg-accent transition-[width] duration-500" :style="{ width: `${scanPercent}%` }" />
        </div>
      </div>

      <main id="main" tabindex="-1" class="min-h-0 flex-1 overflow-y-auto pb-[calc(4rem+env(safe-area-inset-bottom))] focus:outline-none md:pb-0">
        <!-- The SSH page stays alive after the first visit, so open terminals keep running elsewhere -->
        <RouterView v-slot="{ Component }">
          <KeepAlive include="SshView">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </div>

    <MobileNav />
  </div>

  <ToastHost />
  <ConfirmHost />
</template>
