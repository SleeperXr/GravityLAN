<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { api } from '@/api/client';
import type { ApiTokenResponse } from '@/types';
import Card from '@/components/ui/card/Card.vue';
import Button from '@/components/ui/button/Button.vue';
import Input from '@/components/ui/input/Input.vue';
import Badge from '@/components/ui/badge/Badge.vue';

const settings = ref<Record<string, string>>({});
const tokens = ref<ApiTokenResponse[]>([]);
const newTokenName = ref('');
const createdTokenSecret = ref<string | null>(null);
const saving = ref(false);

async function loadSettings() {
  const [s, t] = await Promise.all([api.getSettings(), api.getApiTokens()]);
  settings.value = s;
  tokens.value = t;
}

async function saveSystemSettings() {
  saving.value = true;
  try {
    await api.updateSettings(settings.value);
  } finally {
    saving.value = false;
  }
}

async function handleCreateToken() {
  if (!newTokenName.value.trim()) return;
  const created = await api.createApiToken(newTokenName.value.trim());
  createdTokenSecret.value = created.token;
  newTokenName.value = '';
  tokens.value = await api.getApiTokens();
}

onMounted(loadSettings);
</script>

<template>
  <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
    <Card class="p-5 space-y-4">
      <div>
        <h3 class="text-sm font-semibold text-[#E6EAF0]">Scanner & System-Parameter</h3>
        <p class="text-xs text-[#9AA5B4]">Direkte Konfiguration der GravityLAN Backend-Settings</p>
      </div>

      <div class="space-y-3">
        <div class="space-y-1">
          <label class="text-xs text-[#9AA5B4]">Scan-Intervall (Minuten, 0 = deaktiviert)</label>
          <Input v-model="settings['scan_interval']" type="number" />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-[#9AA5B4]">DNS-Server</label>
          <Input v-model="settings['dns_server']" placeholder="System-Standard" />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-[#9AA5B4]">Offline-Schwellenwert (Fehlversuche)</label>
          <Input v-model="settings['scan.offline_threshold']" type="number" />
        </div>
      </div>

      <Button :disabled="saving" @click="saveSystemSettings">
        {{ saving ? 'Speichere...' : 'Einstellungen speichern' }}
      </Button>
    </Card>

    <Card class="p-5 space-y-4">
      <div>
        <h3 class="text-sm font-semibold text-[#E6EAF0]">API-Tokens (Read-Only)</h3>
        <p class="text-xs text-[#9AA5B4]">Für Python-Client (`gravitylan_api`) und externe Integrationen</p>
      </div>

      <div class="flex gap-2">
        <Input v-model="newTokenName" placeholder="Token-Bezeichnung (z. B. HomeAssistant)" />
        <Button @click="handleCreateToken">Erstellen</Button>
      </div>

      <div
        v-if="createdTokenSecret"
        class="rounded-md border border-[#3DB8F5]/40 bg-[#3DB8F5]/10 p-3 font-mono text-xs text-[#3DB8F5] break-all"
      >
        Neues Token (nur einmal sichtbar): {{ createdTokenSecret }}
      </div>

      <div class="divide-y divide-[#1F2732] rounded-md border border-[#1F2732]">
        <div
          v-for="tok in tokens"
          :key="tok.id"
          class="flex items-center justify-between px-3 py-2 text-xs"
        >
          <div>
            <span class="font-medium text-[#E6EAF0]">{{ tok.name }}</span>
            <span class="ml-2 font-mono text-[#8390A0]">{{ tok.prefix }}…</span>
          </div>
          <Badge variant="secondary">{{ tok.created_at }}</Badge>
        </div>
      </div>
    </Card>
  </div>
</template>
