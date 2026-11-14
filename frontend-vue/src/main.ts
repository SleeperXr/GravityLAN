import '@fontsource-variable/hanken-grotesk';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import './index.css';
import './i18n';
import './composables/useTheme';

import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { router } from './router';

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount('#app');

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/frontend-vue/sw.js', { scope: '/frontend-vue/' }).catch(() => {
      // Service worker registration is non-critical (e.g. insecure HTTP in local lab)
    });
  });
}
