<script setup lang="ts">
import { ref } from 'vue';
import { AlertTriangle, Lock } from 'lucide-vue-next';
import { api } from '@/api/client';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';

const emit = defineEmits<{ authenticated: [] }>();

const password = ref('');
const loading = ref(false);
const error = ref<string | null>(null);
/** GRAVITYLAN_SECURE_COOKIES over plain HTTP: the browser drops the cookie, so the login would not stick. */
const cookieDropped = ref(false);

async function submit() {
  if (!password.value) return;
  loading.value = true;
  error.value = null;
  cookieDropped.value = false;
  try {
    const res = await api.login(password.value);
    if (res?.secure_cookie_over_http) {
      // Going on would only show this screen again; say why instead
      cookieDropped.value = true;
      return;
    }
    password.value = '';
    emit('authenticated');
  } catch {
    error.value = t('auth.invalid_password');
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-dvh items-center justify-center bg-canvas px-4 py-10">
    <div class="w-full max-w-sm">
      <div class="mb-6 flex items-center gap-2.5">
        <div class="flex size-9 items-center justify-center rounded-md border border-accent/30 bg-accent/10 text-accent-text">
          <Lock class="size-4" aria-hidden="true" />
        </div>
        <div>
          <p class="text-sm font-semibold text-fg">{{ t('app.title') }}</p>
          <p class="text-xs text-fg-subtle">{{ t('auth.security_node') }}</p>
        </div>
      </div>

      <div class="gl-card p-6">
        <h1 class="text-lg font-semibold text-fg">{{ t('auth.required') }}</h1>
        <p class="mt-1.5 text-sm leading-relaxed text-fg-muted">{{ t('auth.description') }}</p>

        <div
          v-if="cookieDropped"
          role="alert"
          data-test="secure-cookie-over-http"
          class="mt-4 flex gap-2 rounded-md border border-warn/40 bg-warn/[0.07] p-3 text-xs leading-relaxed text-fg"
        >
          <AlertTriangle class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
          <p>{{ t('gv.auth.secure_cookie_over_http') }}</p>
        </div>

        <form class="mt-5 space-y-4" @submit.prevent="submit">
          <Field v-slot="{ id, describedBy, invalid }" :label="t('auth.password_placeholder')" :error="error">
            <Input
              :id="id"
              v-model="password"
              type="password"
              autocomplete="current-password"
              :aria-describedby="describedBy"
              :invalid="invalid"
              :disabled="loading"
              autofocus
            />
          </Field>
          <Button type="submit" variant="primary" size="lg" class="w-full" :loading="loading" :disabled="!password">
            {{ t('auth.sign_in') }}
          </Button>
        </form>
      </div>
    </div>
  </main>
</template>
