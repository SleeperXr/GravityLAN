<script setup lang="ts">
import { ref, watch } from 'vue';
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
  TabsRoot,
  TabsList,
  TabsTrigger,
  TabsContent,
} from 'reka-ui';
import { X, ExternalLink, RefreshCw, Save, Server, ShieldCheck } from 'lucide-vue-next';
import type { Device, DeviceGroup } from '@/types';
import { api } from '@/api/client';
import { useI18n } from '@/composables/useI18n';
import Button from '@/components/ui/button/Button.vue';
import Badge from '@/components/ui/badge/Badge.vue';
import Input from '@/components/ui/input/Input.vue';

const props = defineProps<{
  device: Device | null;
  groups: DeviceGroup[];
  open: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void;
  (e: 'saved'): void;
}>();

const { t } = useI18n();
const displayName = ref('');
const selectedGroupId = ref<number | null>(null);
const notes = ref('');
const saving = ref(false);
const rescanning = ref(false);

watch(
  () => props.device,
  (dev) => {
    if (dev) {
      displayName.value = dev.display_name;
      selectedGroupId.value = dev.group_id;
      notes.value = dev.notes ?? '';
    }
  },
  { immediate: true }
);

async function saveChanges() {
  if (!props.device) return;
  saving.value = true;
  try {
    await api.updateDevice(props.device.id, {
      display_name: displayName.value,
      group_id: selectedGroupId.value,
      notes: notes.value,
    });
    emit('saved');
    emit('update:open', false);
  } finally {
    saving.value = false;
  }
}

async function rescanPorts() {
  if (!props.device) return;
  rescanning.value = true;
  try {
    await api.refreshServices(props.device.id);
    emit('saved');
  } finally {
    rescanning.value = false;
  }
}
</script>

<template>
  <DialogRoot :open="props.open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/65 backdrop-blur-xs" />
      <DialogContent
        v-if="props.device"
        class="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-[#2A3340] bg-[#151A21] p-6 text-[#E6EAF0] shadow-2xl focus:outline-none"
      >
        <div class="flex items-start justify-between border-b border-[#1F2732] pb-4">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <DialogTitle class="text-base font-semibold text-[#E6EAF0]">
                {{ props.device.display_name }}
              </DialogTitle>
              <Badge :variant="props.device.is_online ? 'success' : 'destructive'">
                {{ props.device.is_online ? 'Online' : 'Offline' }}
              </Badge>
            </div>
            <DialogDescription class="font-mono text-xs text-[#9AA5B4]">
              {{ props.device.ip }}
              <span v-if="props.device.mac"> · {{ props.device.mac }}</span>
              <span v-if="props.device.vendor"> · {{ props.device.vendor }}</span>
            </DialogDescription>
          </div>
          <DialogClose
            class="rounded-md p-1.5 text-[#9AA5B4] hover:bg-[#1F2732] hover:text-[#E6EAF0] cursor-pointer"
          >
            <X class="h-4 w-4" />
          </DialogClose>
        </div>

        <TabsRoot default-value="overview" class="mt-4 flex flex-1 flex-col overflow-hidden">
          <TabsList class="grid w-full grid-cols-3 rounded-md bg-[#0E1116] p-1 border border-[#1F2732]">
            <TabsTrigger
              value="overview"
              class="rounded-xs py-1.5 text-xs font-medium text-[#9AA5B4] data-[state=active]:bg-[#1F2732] data-[state=active]:text-[#E6EAF0] cursor-pointer"
            >
              {{ t('sheet.overview') }}
            </TabsTrigger>
            <TabsTrigger
              value="services"
              class="rounded-xs py-1.5 text-xs font-medium text-[#9AA5B4] data-[state=active]:bg-[#1F2732] data-[state=active]:text-[#E6EAF0] cursor-pointer"
            >
              {{ t('sheet.services') }} ({{ props.device.services?.length ?? 0 }})
            </TabsTrigger>
            <TabsTrigger
              value="agent"
              class="rounded-xs py-1.5 text-xs font-medium text-[#9AA5B4] data-[state=active]:bg-[#1F2732] data-[state=active]:text-[#E6EAF0] cursor-pointer"
            >
              {{ t('sheet.agent') }}
            </TabsTrigger>
          </TabsList>

          <!-- Tab 1: Overview -->
          <TabsContent value="overview" class="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-[#9AA5B4]">Anzeigename</label>
              <Input v-model="displayName" />
            </div>

            <div class="space-y-1.5">
              <label class="text-xs font-medium text-[#9AA5B4]">Gruppe</label>
              <select
                v-model="selectedGroupId"
                class="flex h-8 w-full rounded-md border border-[#2A3340] bg-[#0B0E13] px-3 text-xs text-[#E6EAF0] focus:border-[#3DB8F5] focus:outline-none"
              >
                <option :value="null">Keine Gruppe</option>
                <option v-for="g in props.groups" :key="g.id" :value="g.id">
                  {{ g.name }}
                </option>
              </select>
            </div>

            <div class="grid grid-cols-2 gap-3 rounded-md border border-[#1F2732] bg-[#0E1116] p-3 text-xs">
              <div>
                <span class="text-[#8390A0] block">Hostname</span>
                <span class="font-mono text-[#E6EAF0]">{{ props.device.hostname || '—' }}</span>
              </div>
              <div>
                <span class="text-[#8390A0] block">Gerätetyp</span>
                <span class="font-mono text-[#E6EAF0]">{{ props.device.device_type || 'generic' }}</span>
              </div>
              <div>
                <span class="text-[#8390A0] block">Subnetz</span>
                <span class="font-mono text-[#E6EAF0]">{{ props.device.subnet_name || 'Standard' }}</span>
              </div>
              <div>
                <span class="text-[#8390A0] block">Zuletzt gesehen</span>
                <span class="font-mono text-[#E6EAF0]">{{ props.device.last_seen || '—' }}</span>
              </div>
            </div>

            <div class="space-y-1.5">
              <label class="text-xs font-medium text-[#9AA5B4]">Notizen</label>
              <textarea
                v-model="notes"
                rows="3"
                class="w-full rounded-md border border-[#2A3340] bg-[#0B0E13] p-2.5 text-xs text-[#E6EAF0] focus:border-[#3DB8F5] focus:outline-none"
              />
            </div>

            <Button class="w-full" :disabled="saving" @click="saveChanges">
              <Save class="h-3.5 w-3.5" />
              {{ t('sheet.save') }}
            </Button>
          </TabsContent>

          <!-- Tab 2: Services -->
          <TabsContent value="services" class="mt-4 flex-1 space-y-3 overflow-y-auto pr-1">
            <div class="flex items-center justify-between">
              <span class="text-xs text-[#9AA5B4]">Erkannte Ports & Web-Oberflächen</span>
              <Button variant="outline" size="sm" :disabled="rescanning" @click="rescanPorts">
                <RefreshCw class="h-3 w-3" :class="rescanning ? 'animate-spin' : ''" />
                {{ t('sheet.refresh_services') }}
              </Button>
            </div>

            <div v-if="!props.device.services?.length" class="rounded-md border border-[#1F2732] bg-[#0E1116] p-6 text-center text-xs text-[#8390A0]">
              Keine Dienste für dieses Gerät hinterlegt.
            </div>

            <div
              v-for="svc in props.device.services"
              :key="svc.id"
              class="flex items-center justify-between rounded-md border border-[#1F2732] bg-[#0E1116] px-3 py-2.5"
            >
              <div class="space-y-0.5">
                <div class="flex items-center gap-2">
                  <span class="text-xs font-medium text-[#E6EAF0]">{{ svc.name }}</span>
                  <Badge :variant="svc.is_up ? 'success' : 'secondary'" class="font-mono text-[10px]">
                    :{{ svc.port }}/{{ svc.protocol }}
                  </Badge>
                </div>
                <p v-if="svc.ssl_expiry_days !== null && svc.ssl_expiry_days !== undefined" class="text-[11px] text-[#8390A0]">
                  SSL gültig für {{ svc.ssl_expiry_days }} Tage
                </p>
              </div>
              <a
                v-if="svc.protocol === 'http' || svc.protocol === 'https'"
                :href="`${svc.protocol}://${props.device.ip}:${svc.port}`"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 rounded-md border border-[#2A3340] bg-[#151A21] px-2.5 py-1 text-xs text-[#3DB8F5] hover:bg-[#1F2732]"
              >
                Öffnen
                <ExternalLink class="h-3 w-3" />
              </a>
            </div>
          </TabsContent>

          <!-- Tab 3: Agent -->
          <TabsContent value="agent" class="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
            <div v-if="props.device.has_agent && props.device.agent_info" class="space-y-3">
              <div class="flex items-center justify-between rounded-md border border-[#2EA043]/30 bg-[#2EA043]/10 p-3">
                <div class="flex items-center gap-2.5">
                  <ShieldCheck class="h-4 w-4 text-[#4AC26B]" />
                  <div>
                    <p class="text-xs font-semibold text-[#E6EAF0]">Linux-Agent aktiv</p>
                    <p class="font-mono text-[11px] text-[#9AA5B4]">
                      Version {{ props.device.agent_info.agent_version || 'unbekannt' }}
                    </p>
                  </div>
                </div>
              </div>

              <div v-if="props.device.agent_info.metrics" class="grid grid-cols-3 gap-2.5">
                <div class="rounded-md border border-[#1F2732] bg-[#0E1116] p-3">
                  <span class="text-[11px] text-[#8390A0] block">CPU-Last</span>
                  <span class="font-mono text-sm font-semibold text-[#3DB8F5]">
                    {{ props.device.agent_info.metrics.cpu_usage.toFixed(1) }}%
                  </span>
                </div>
                <div class="rounded-md border border-[#1F2732] bg-[#0E1116] p-3">
                  <span class="text-[11px] text-[#8390A0] block">RAM</span>
                  <span class="font-mono text-sm font-semibold text-[#E6EAF0]">
                    {{ props.device.agent_info.metrics.memory_usage.toFixed(1) }}%
                  </span>
                </div>
                <div class="rounded-md border border-[#1F2732] bg-[#0E1116] p-3">
                  <span class="text-[11px] text-[#8390A0] block">Disk</span>
                  <span class="font-mono text-sm font-semibold text-[#E6EAF0]">
                    {{ props.device.agent_info.metrics.disk_usage.toFixed(1) }}%
                  </span>
                </div>
              </div>
            </div>

            <div v-else class="rounded-md border border-[#1F2732] bg-[#0E1116] p-5 text-center space-y-2">
              <Server class="mx-auto h-6 w-6 text-[#8390A0]" />
              <p class="text-xs font-medium text-[#E6EAF0]">Kein aktiver Agent verbunden</p>
              <p class="text-[11px] text-[#8390A0]">
                Für SSH-Rollout oder Einmal-Installationscode kannst du jederzeit mit einem Klick ins Legacy-UI wechseln.
              </p>
            </div>
          </TabsContent>
        </TabsRoot>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
