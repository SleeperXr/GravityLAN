<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { AlertTriangle } from 'lucide-vue-next';
import { api } from '@/api/client';
import { t } from '@/i18n';

/** Over HTTPS without GRAVITYLAN_SECURE_COOKIES the login cookie may also travel over plain HTTP; say so. */
const show = ref(false);

onMounted(async () => {
  try {
    const status = await api.getCookieSecurity();
    // The browser knows best whether this page came over HTTPS; the server also sees a proxy's X-Forwarded-Proto
    const overHttps = window.location.protocol === 'https:' || status.https;
    show.value = overHttps && !status.secure_cookies;
  } catch {
    show.value = false;
  }
});
</script>

<template>
  <div
    v-if="show"
    role="status"
    data-test="cookie-insecure"
    class="flex gap-2 rounded-md border border-warn/40 bg-warn/[0.07] p-3 text-xs leading-relaxed text-fg"
  >
    <AlertTriangle class="mt-0.5 size-4 shrink-0 text-warn-text" aria-hidden="true" />
    <p class="max-w-prose">{{ t('settings.password.cookie_insecure') }}</p>
  </div>
</template>
