<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Network, Server } from 'lucide-vue-next';
import type { Device } from '@/types';
import { useNetworkStore } from '@/stores/network';
import PageHeader from '@/components/ui/PageHeader.vue';
import NetzPlan from '@/components/netzplan/NetzPlan.vue';
import RackView from '@/components/racks/RackView.vue';
import DeviceEditor from '@/components/editor/DeviceEditor.vue';
import { t } from '@/i18n';

/** Topology: the editable network map, or the racks (same records as the React topology). */
const store = useNetworkStore();
const route = useRoute();
const router = useRouter();
const editorDevice = ref<Device | null>(null);
const editorOpen = ref(false);

// The view is in the URL (?view=rack), so it survives a reload and can be linked
const view = computed<'map' | 'rack'>({
  get: () => (route.query.view === 'rack' ? 'rack' : 'map'),
  set: (next) => void router.replace({ query: next === 'rack' ? { view: 'rack' } : {} }),
});

function openDevice(device: Device) {
  editorDevice.value = device;
  editorOpen.value = true;
}

const views = [
  { id: 'map' as const, icon: Network, label: 'topology.tab_map' },
  { id: 'rack' as const, icon: Server, label: 'topology.tab_rack' },
];
</script>

<template>
  <div class="flex h-full flex-col gap-4 px-4 py-5 md:px-8 md:py-7">
    <PageHeader
      :title="view === 'rack' ? t('topology.tab_rack') : t('gv.plan.title')"
      :description="view === 'rack' ? t('gv.racks.subtitle') : t('gv.plan.subtitle', { devices: store.totalCount })"
    >
      <div class="flex rounded-md border border-line bg-sunken p-0.5" role="group" :aria-label="t('topology.view_label')">
        <button
          v-for="v in views"
          :key="v.id"
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-xs font-semibold transition-colors"
          :class="view === v.id ? 'bg-control text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
          :aria-pressed="view === v.id"
          @click="view = v.id"
        >
          <component :is="v.icon" class="size-3.5" aria-hidden="true" />{{ t(v.label) }}
        </button>
      </div>
    </PageHeader>
    <div class="gl-card min-h-[28rem] flex-1 overflow-hidden">
      <NetzPlan v-if="view === 'map'" editable flow-id="topology" @open-device="openDevice" />
      <RackView v-else :devices="store.devices" @open-device="openDevice" @changed="store.loadData(true)" />
    </div>
    <DeviceEditor v-if="editorDevice" v-model:open="editorOpen" :device="editorDevice" @saved="store.loadData(true)" @after-leave="editorDevice = null" />
  </div>
</template>
