import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from '@/views/DashboardView.vue';
import HealthView from '@/views/HealthView.vue';
import NetworkView from '@/views/NetworkView.vue';
import AgentsView from '@/views/AgentsView.vue';
import SettingsView from '@/views/SettingsView.vue';

export const router = createRouter({
  history: createWebHistory('/frontend-vue/'),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/health', name: 'health', component: HealthView },
    { path: '/network', name: 'network', component: NetworkView },
    { path: '/agents', name: 'agents', component: AgentsView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});
