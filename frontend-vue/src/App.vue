<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { RefreshCw } from 'lucide-vue-next';
import { api } from '@/api/client';
import { useNetworkStore } from '@/stores/network';
import AppSidebar from '@/components/layout/AppSidebar.vue';
import AppHeader from '@/components/layout/AppHeader.vue';
import LoginDialog from '@/components/auth/LoginDialog.vue';

const store = useNetworkStore();
const authState = ref<'checking' | 'authenticated' | 'unauthenticated'>('checking');
const appVersion = ref<string | undefined>(undefined);

async function bootstrap() {
  authState.value = 'checking';
  try {
    const setup = await api.getSetupStatus();
    appVersion.value = setup.version;
    if (!setup.is_setup_complete) {
      window.location.href = '/';
      return;
    }
    await api.checkAuth();
    authState.value = 'authenticated';
    await store.fetchInventory(true);
    store.connectScanStream();
  } catch {
    authState.value = 'unauthenticated';
  }
}

onMounted(bootstrap);
onBeforeUnmount(() => store.disconnectScanStream());
</script>

<template>
  <div
    v-if="authState === 'checking'"
    class="flex h-screen w-screen items-center justify-center bg-[#0a0a0c] text-zinc-400 gap-2.5 text-xs"
  >
    <RefreshCw class="h-4 w-4 animate-spin text-emerald-400" />
    <span>Loading GravityUI...</span>
  </div>

  <LoginDialog v-else-if="authState === 'unauthenticated'" @authenticated="bootstrap" />

  <div v-else class="flex h-screen w-screen overflow-hidden bg-[#0a0a0c] text-zinc-100">
    <AppSidebar :version="appVersion" />
    <div class="flex flex-1 flex-col overflow-hidden">
      <AppHeader />
      <main class="flex-1 overflow-y-auto">
        <RouterView />
      </main>
    </div>
  </div>
</template>
