<script setup lang="ts">
import { ref } from 'vue';
import type { Device } from '@/types';
import { useNetworkStore } from '@/stores/network';
import PageHeader from '@/components/ui/PageHeader.vue';
import NetzPlan from '@/components/netzplan/NetzPlan.vue';
import DeviceEditor from '@/components/editor/DeviceEditor.vue';
import { t } from '@/i18n';

/** Topology: the network map, full height, editable (same records as the React topology). */
const store = useNetworkStore();
const editorDevice = ref<Device | null>(null);
const editorOpen = ref(false);

function openDevice(device: Device) {
  editorDevice.value = device;
  editorOpen.value = true;
}
</script>

<template>
  <div class="flex h-full flex-col gap-4 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('gv.plan.title')" :description="t('gv.plan.subtitle', { devices: store.totalCount })" />
    <div class="gl-card min-h-[28rem] flex-1 overflow-hidden">
      <NetzPlan editable flow-id="topology" @open-device="openDevice" />
    </div>
    <DeviceEditor v-if="editorDevice" v-model:open="editorOpen" :device="editorDevice" @saved="store.loadData(true)" @after-leave="editorDevice = null" />
  </div>
</template>
