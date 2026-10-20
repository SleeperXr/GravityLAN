<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Check, Copy, KeyRound, Sliders, Trash2 } from 'lucide-vue-next';
import RelativeTime from '@/components/8starlabs-ui/RelativeTime.vue';
import { api } from '@/api/client';
import type { ApiTokenResponse } from '@/types';

const settings = ref<Record<string, string>>({});
const tokens = ref<ApiTokenResponse[]>([]);
const newTokenName = ref('');
const createdTokenSecret = ref<string | null>(null);
const copiedToken = ref(false);
const saving = ref(false);
const savedSuccess = ref(false);

async function loadSettings() {
  const [s, t] = await Promise.all([api.getSettings(), api.getApiTokens()]);
  settings.value = s;
  tokens.value = t;
}

async function saveSystemSettings() {
  saving.value = true;
  savedSuccess.value = false;
  try {
    await api.updateSettings(settings.value);
    savedSuccess.value = true;
    setTimeout(() => {
      savedSuccess.value = false;
    }, 2000);
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

async function handleDeleteToken(id: number) {
  await api.deleteApiToken(id);
  tokens.value = await api.getApiTokens();
}

function copyToken() {
  if (!createdTokenSecret.value) return;
  navigator.clipboard?.writeText(createdTokenSecret.value).then(() => {
    copiedToken.value = true;
    setTimeout(() => {
      copiedToken.value = false;
    }, 2000);
  });
}

onMounted(loadSettings);
</script>

<template>
  <div class="p-6 max-w-[1640px] mx-auto space-y-6">
    <div>
      <h2 class="text-lg font-bold text-zinc-100 tracking-tight">System Settings & API Keys</h2>
      <p class="text-xs text-zinc-400">
        Configure background discovery intervals, DNS resolvers & read-only API tokens
      </p>
    </div>

    <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <!-- Scanner & System Parameters Card -->
      <div class="sh-card p-6 space-y-5">
        <div class="flex items-center gap-2.5">
          <div class="w-9 h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 flex items-center justify-center">
            <Sliders class="w-4 h-4 text-emerald-400" />
          </div>
          <div>
            <h3 class="text-sm font-bold text-zinc-100">Scanner & Telemetry Engine</h3>
            <p class="text-xs text-zinc-400">Shared configuration with the FastAPI backend</p>
          </div>
        </div>

        <div class="space-y-4">
          <div class="sh-subcard p-3.5 space-y-1.5">
            <label class="block text-xs font-semibold text-zinc-200">
              Automatic Scan Interval (Minutes, 0 = disabled)
            </label>
            <input
              v-model="settings['scan_interval']"
              type="number"
              class="w-full h-9 rounded-lg bg-[#131316] border border-zinc-800 px-3 text-xs font-mono text-zinc-100"
            />
          </div>

          <div class="sh-subcard p-3.5 space-y-1.5">
            <label class="block text-xs font-semibold text-zinc-200">Custom DNS Server for Reverse Lookups</label>
            <input
              v-model="settings['dns_server']"
              placeholder="e.g. 192.168.1.1 (System Default if empty)"
              class="w-full h-9 rounded-lg bg-[#131316] border border-zinc-800 px-3 text-xs font-mono text-zinc-100"
            />
          </div>

          <div class="sh-subcard p-3.5 space-y-1.5">
            <label class="block text-xs font-semibold text-zinc-200">
              Offline Hysteresis Threshold (Missed Scans before Offline)
            </label>
            <input
              v-model="settings['scan.offline_threshold']"
              type="number"
              class="w-full h-9 rounded-lg bg-[#131316] border border-zinc-800 px-3 text-xs font-mono text-zinc-100"
            />
          </div>
        </div>

        <button
          type="button"
          class="w-full h-10 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold text-xs transition-colors cursor-pointer"
          :disabled="saving"
          @click="saveSystemSettings"
        >
          {{ saving ? 'Saving Settings...' : savedSuccess ? '✓ Settings Saved' : 'Save System Configuration' }}
        </button>
      </div>

      <!-- API Tokens Card -->
      <div class="sh-card p-6 space-y-5">
        <div class="flex items-center gap-2.5">
          <div class="w-9 h-9 rounded-xl bg-[#1b1b20] border border-zinc-800 flex items-center justify-center">
            <KeyRound class="w-4 h-4 text-sky-400" />
          </div>
          <div>
            <h3 class="text-sm font-bold text-zinc-100">Read-Only API Tokens</h3>
            <p class="text-xs text-zinc-400">For `gravitylan_api` Python SDK, HomeAssistant & scripts</p>
          </div>
        </div>

        <div class="flex gap-2">
          <input
            v-model="newTokenName"
            placeholder="Token label (e.g. HomeAssistant, Grafana)"
            class="flex-1 h-10 rounded-xl bg-[#1b1b20] border border-zinc-800 px-3 text-xs text-zinc-100"
            @keyup.enter="handleCreateToken"
          />
          <button
            type="button"
            class="px-4 h-10 rounded-xl bg-zinc-100 hover:bg-white text-zinc-950 font-semibold text-xs cursor-pointer"
            @click="handleCreateToken"
          >
            Create Token
          </button>
        </div>

        <div
          v-if="createdTokenSecret"
          class="sh-subcard p-3.5 border-emerald-500/40 bg-emerald-950/20 space-y-2"
        >
          <div class="flex items-center justify-between text-xs">
            <span class="font-semibold text-emerald-400">New Token (copy now, shown once):</span>
            <button
              type="button"
              class="inline-flex items-center gap-1 text-xs text-zinc-200 hover:text-white cursor-pointer"
              @click="copyToken"
            >
              <Check v-if="copiedToken" class="w-3.5 h-3.5 text-emerald-400" />
              <Copy v-else class="w-3.5 h-3.5" />
              {{ copiedToken ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <div class="font-mono text-xs text-zinc-100 break-all p-2 rounded-lg bg-[#0d0d10] border border-zinc-800">
            {{ createdTokenSecret }}
          </div>
        </div>

        <div class="space-y-2">
          <div
            v-for="tok in tokens"
            :key="tok.id"
            class="sh-subcard p-3 flex items-center justify-between text-xs"
          >
            <div>
              <span class="font-semibold text-zinc-100">{{ tok.name }}</span>
              <span class="ml-2 font-mono text-zinc-500">{{ tok.prefix }}…</span>
            </div>
            <div class="flex items-center gap-3">
              <RelativeTime :date="tok.created_at" />
              <button
                type="button"
                class="p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 cursor-pointer"
                @click="handleDeleteToken(tok.id)"
              >
                <Trash2 class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
