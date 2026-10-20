import { ref, computed } from 'vue';

export type Locale = 'de' | 'en';

const initialLocale = (): Locale => {
  const stored = localStorage.getItem('i18nextLng') || navigator.language || 'de';
  return stored.toLowerCase().startsWith('de') ? 'de' : 'en';
};

const currentLocale = ref<Locale>(initialLocale());

const messages: Record<Locale, Record<string, string>> = {
  de: {
    'app.subtitle': 'Standard Dashboard (shadcn-vue)',
    'nav.dashboard': 'Übersicht',
    'nav.health': 'Health-Radar',
    'nav.network': 'IP & Subnetze',
    'nav.agents': 'Linux-Agents',
    'nav.settings': 'Einstellungen',
    'nav.legacy_switch': 'Zu Legacy UI wechseln',
    'nav.legacy_badge': 'React',
    'nav.open_legacy': 'Im Legacy UI öffnen',
    'kpi.total_devices': 'Inventarisierte Geräte',
    'kpi.online_status': 'Online / Erreichbar',
    'kpi.active_agents': 'Aktive Linux-Agents',
    'kpi.subnets_active': 'Scan-Subnetze',
    'kpi.health_score': 'Netzwerk Health-Score',
    'kpi.avg_latency': 'Ø Latenz / Jitter',
    'kpi.active_issues': 'Offene Warnungen',
    'dashboard.title': 'Netzwerk-Inventar & Standard-Dashboard',
    'dashboard.subtitle': 'Strukturierte Echtzeit-Übersicht aller erkannten Hosts, Dienste und Agent-Metriken',
    'dashboard.search': 'Suche nach Name, IP, MAC, Hersteller oder Gruppe...',
    'dashboard.all_groups': 'Alle Gruppen',
    'dashboard.status_all': 'Alle Status',
    'dashboard.status_online': 'Nur Online',
    'dashboard.status_offline': 'Nur Offline',
    'dashboard.view_table': 'Tabelle',
    'dashboard.view_cards': 'Karten',
    'dashboard.scan_now': 'Scan starten',
    'dashboard.scanning': 'Scan läuft...',
    'dashboard.refresh': 'Aktualisieren',
    'table.device': 'Gerät',
    'table.ip_mac': 'IP / MAC',
    'table.group': 'Gruppe',
    'table.status': 'Status',
    'table.services': 'Dienste',
    'table.agent': 'Agent (CPU / RAM)',
    'table.actions': 'Details',
    'sheet.overview': 'Stammdaten',
    'sheet.services': 'Dienste & Ports',
    'sheet.agent': 'Agent & Telemetrie',
    'sheet.save': 'Änderungen speichern',
    'sheet.refresh_services': 'Ports neu prüfen',
    'auth.title': 'GravityUI Anmeldung',
    'auth.desc': 'Melde dich mit deinem GravityLAN Administrator-Passwort an.',
    'auth.password': 'Admin-Passwort',
    'auth.submit': 'Anmelden',
  },
  en: {
    'app.subtitle': 'Standard Dashboard (shadcn-vue)',
    'nav.dashboard': 'Overview',
    'nav.health': 'Health Radar',
    'nav.network': 'IP & Subnets',
    'nav.agents': 'Linux Agents',
    'nav.settings': 'Settings',
    'nav.legacy_switch': 'Switch to Legacy UI',
    'nav.legacy_badge': 'React',
    'nav.open_legacy': 'Open in Legacy UI',
    'kpi.total_devices': 'Total Devices',
    'kpi.online_status': 'Online / Reachable',
    'kpi.active_agents': 'Active Linux Agents',
    'kpi.subnets_active': 'Scan Subnets',
    'kpi.health_score': 'Network Health Score',
    'kpi.avg_latency': 'Avg Latency / Jitter',
    'kpi.active_issues': 'Active Warnings',
    'dashboard.title': 'Network Inventory & Standard Dashboard',
    'dashboard.subtitle': 'Structured real-time overview of all discovered hosts, services, and agent metrics',
    'dashboard.search': 'Search by name, IP, MAC, vendor, or group...',
    'dashboard.all_groups': 'All Groups',
    'dashboard.status_all': 'All States',
    'dashboard.status_online': 'Online Only',
    'dashboard.status_offline': 'Offline Only',
    'dashboard.view_table': 'Table',
    'dashboard.view_cards': 'Cards',
    'dashboard.scan_now': 'Run Scan',
    'dashboard.scanning': 'Scanning...',
    'dashboard.refresh': 'Refresh',
    'table.device': 'Device',
    'table.ip_mac': 'IP / MAC',
    'table.group': 'Group',
    'table.status': 'Status',
    'table.services': 'Services',
    'table.agent': 'Agent (CPU / RAM)',
    'table.actions': 'Details',
    'sheet.overview': 'General',
    'sheet.services': 'Services & Ports',
    'sheet.agent': 'Agent & Telemetry',
    'sheet.save': 'Save changes',
    'sheet.refresh_services': 'Rescan ports',
    'auth.title': 'GravityUI Sign In',
    'auth.desc': 'Sign in with your GravityLAN administrator password.',
    'auth.password': 'Admin password',
    'auth.submit': 'Sign in',
  },
};

export function useI18n() {
  const locale = computed(() => currentLocale.value);

  function setLocale(next: Locale) {
    currentLocale.value = next;
    localStorage.setItem('i18nextLng', next);
  }

  function toggleLocale() {
    setLocale(currentLocale.value === 'de' ? 'en' : 'de');
  }

  function t(key: string): string {
    return messages[currentLocale.value][key] ?? key;
  }

  return {
    locale,
    setLocale,
    toggleLocale,
    t,
  };
}
