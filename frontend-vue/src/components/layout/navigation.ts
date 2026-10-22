import type { Component } from 'vue';
import { Activity, Grid3x3, LayoutDashboard, Network, ScrollText, Server, Settings, SquareTerminal } from 'lucide-vue-next';

export interface NavItem {
  id: string;
  to: string;
  icon: Component;
  /** i18n key, shared with the React sidebar */
  label: string;
  /** Line colour of the page's sign (--line-N), so the navigation reads like a route map */
  line: number;
}

/** Same destinations and order as the React sidebar (frontend/src/components/Sidebar.tsx). */
export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', to: '/', icon: LayoutDashboard, label: 'sidebar.dashboard', line: 1 },
  { id: 'health', to: '/health', icon: Activity, label: 'sidebar.health', line: 5 },
  { id: 'network', to: '/network', icon: Grid3x3, label: 'sidebar.network_planner', line: 3 },
  { id: 'topology', to: '/topology', icon: Network, label: 'sidebar.topology', line: 4 },
  { id: 'agents', to: '/agents', icon: Server, label: 'sidebar.agents', line: 2 },
  { id: 'ssh', to: '/ssh', icon: SquareTerminal, label: 'sidebar.ssh', line: 6 },
  { id: 'logs', to: '/logs', icon: ScrollText, label: 'sidebar.logs', line: 9 },
  { id: 'settings', to: '/settings', icon: Settings, label: 'sidebar.settings', line: 8 },
];

export const lineVar = (item: Pick<NavItem, 'line'>) => `var(--line-${item.line})`;
/** The line colour as icon/text ink: pulled a quarter towards the text colour, so light lines stay readable */
export const lineInk = (item: Pick<NavItem, 'line'>) => `color-mix(in oklab, ${lineVar(item)} 75%, var(--gl-fg))`;

/** Phone tab bar: four destinations plus "More"; the rest opens in the menu sheet. */
export const TAB_IDS = ['dashboard', 'health', 'network', 'agents'] as const;
