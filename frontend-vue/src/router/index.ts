import { createRouter, createWebHistory } from 'vue-router';
import { api } from '@/api/client';

declare module 'vue-router' {
  interface RouteMeta {
    /** Which nav entry is active (see components/layout/navigation.ts) */
    navId?: string;
    /** i18n key for the page title (phone app bar, document title) */
    titleKey?: string;
  }
}

const LegacyOnlyView = () => import('@/views/LegacyOnlyView.vue');

export const router = createRouter({
  history: createWebHistory('/frontend-vue/'),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { navId: 'dashboard', titleKey: 'sidebar.dashboard' } },
    { path: '/health', name: 'health', component: () => import('@/views/HealthView.vue'), meta: { navId: 'health', titleKey: 'sidebar.health' } },
    { path: '/network', name: 'network', component: () => import('@/views/NetworkView.vue'), meta: { navId: 'network', titleKey: 'sidebar.network_planner' } },
    { path: '/topology', name: 'topology', component: LegacyOnlyView, meta: { navId: 'topology', titleKey: 'sidebar.topology' } },
    { path: '/agents', name: 'agents', component: () => import('@/views/AgentsView.vue'), meta: { navId: 'agents', titleKey: 'sidebar.agents' } },
    { path: '/ssh', name: 'ssh', component: LegacyOnlyView, meta: { navId: 'ssh', titleKey: 'sidebar.ssh' } },
    { path: '/logs', name: 'logs', component: LegacyOnlyView, meta: { navId: 'logs', titleKey: 'sidebar.logs' } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { navId: 'settings', titleKey: 'sidebar.settings' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});

/**
 * Optional start page (Settings > `ui.start_page`), applied once per browser session like
 * RootRedirect in the React UI, so clicking "Overview" later does not bounce.
 */
const REDIRECT_FLAG = 'gravitylan_initial_redirect';
router.beforeEach(async (to) => {
  if (to.name !== 'dashboard' || sessionStorage.getItem(REDIRECT_FLAG)) return true;
  sessionStorage.setItem(REDIRECT_FLAG, 'true');
  try {
    const settings = await api.getSettings();
    const page = settings['ui.start_page'] || '/';
    localStorage.setItem('gravitylan_start_page', page);
    if (page === '/health') return { path: '/health', replace: true };
  } catch {
    // Not signed in yet or offline: stay on the overview
  }
  return true;
});
