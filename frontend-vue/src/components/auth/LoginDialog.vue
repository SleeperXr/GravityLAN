<script setup lang="ts">
import { ref } from 'vue';
import { Lock, AlertCircle, ArrowLeftRight } from 'lucide-vue-next';
import { api } from '@/api/client';
import { useI18n } from '@/composables/useI18n';
import Card from '@/components/ui/card/Card.vue';
import Button from '@/components/ui/button/Button.vue';
import Input from '@/components/ui/input/Input.vue';

const emit = defineEmits<{
  (e: 'authenticated'): void;
}>();

const { t } = useI18n();
const password = ref('');
const loading = ref(false);
const errorMessage = ref<string | null>(null);

async function handleSubmit() {
  if (!password.value.trim()) return;
  loading.value = true;
  errorMessage.value = null;
  try {
    await api.login(password.value);
    emit('authenticated');
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Login failed';
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen w-screen items-center justify-center bg-[#0E1116] p-4">
    <Card class="w-full max-w-md border-[#2A3340] bg-[#151A21] p-6 space-y-5">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="flex h-9 w-9 items-center justify-center rounded-md bg-[#3DB8F5]/15 text-[#3DB8F5] border border-[#3DB8F5]/30">
            <Lock class="h-4 w-4" />
          </div>
          <div>
            <h2 class="text-base font-semibold text-[#E6EAF0]">{{ t('auth.title') }}</h2>
            <p class="text-xs text-[#9AA5B4]">{{ t('app.subtitle') }}</p>
          </div>
        </div>
        <a
          href="/"
          class="inline-flex items-center gap-1.5 rounded-md border border-[#2A3340] bg-[#1F2732] px-2.5 py-1 text-[11px] text-[#E6EAF0] hover:border-[#3DB8F5]"
        >
          <ArrowLeftRight class="h-3 w-3 text-[#3DB8F5]" />
          Legacy UI
        </a>
      </div>

      <p class="text-xs text-[#9AA5B4] leading-relaxed">
        {{ t('auth.desc') }}
      </p>

      <form class="space-y-4" @submit.prevent="handleSubmit">
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-[#E6EAF0]">{{ t('auth.password') }}</label>
          <Input
            v-model="password"
            type="password"
            :placeholder="t('auth.password')"
            :disabled="loading"
          />
        </div>

        <div
          v-if="errorMessage"
          class="flex items-center gap-2 rounded-md border border-[#F47067]/30 bg-[#F47067]/10 px-3 py-2 text-xs text-[#F47067]"
        >
          <AlertCircle class="h-4 w-4 shrink-0" />
          <span>{{ errorMessage }}</span>
        </div>

        <Button type="submit" class="w-full" :disabled="loading">
          {{ loading ? '...' : t('auth.submit') }}
        </Button>
      </form>
    </Card>
  </div>
</template>
