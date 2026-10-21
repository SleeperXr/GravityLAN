import type { Component } from 'vue';
import { Activity, Grid3x3, LayoutDashboard, Network, ScrollText, Server, Settings, SquareTerminal } from 'lucide-vue-next';

export interface NavItem {
  id: string;
  to: string;
  icon: Component;
  /** i18n key, shared with the React sidebar */
  label: string;
}

/** Same destinations and order as the React sidebar (frontend/src/components/Sidebar.tsx). */
export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', to: '/', icon: LayoutDashboard, label: 'sidebar.dashboard' },
  { id: 'health', to: '/health', icon: Activity, label: 'sidebar.health' },
  { id: 'network', to: '/network', icon: Grid3x3, label: 'sidebar.network_planner' },
  { id: 'topology', to: '/topology', icon: Network, label: 'sidebar.topology' },
  { id: 'agents', to: '/agents', icon: Server, label: 'sidebar.agents' },
  { id: 'ssh', to: '/ssh', icon: SquareTerminal, label: 'sidebar.ssh' },
  { id: 'logs', to: '/logs', icon: ScrollText, label: 'sidebar.logs' },
  { id: 'settings', to: '/settings', icon: Settings, label: 'sidebar.settings' },
];

/** Phone tab bar: four destinations plus "More"; the rest opens in the menu sheet. */
export const TAB_IDS = ['dashboard', 'health', 'network', 'agents'] as const;
