import { LayoutDashboard, Settings, Network, X, Grid3x3, Server, ScrollText, type LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

interface NavItem {
  id: string;
  to: string;
  icon: LucideIcon;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', to: '/', icon: LayoutDashboard, label: 'sidebar.dashboard' },
  { id: 'network', to: '/network', icon: Grid3x3, label: 'sidebar.network_planner' },
  { id: 'topology', to: '/topology', icon: Network, label: 'sidebar.topology' },
  { id: 'agents', to: '/agents', icon: Server, label: 'sidebar.agents' },
  { id: 'logs', to: '/logs', icon: ScrollText, label: 'sidebar.logs' },
  { id: 'settings', to: '/settings', icon: Settings, label: 'sidebar.settings' },
];

// Bottom bar on phones: five destinations; logs stay reachable via the menu drawer.
const TAB_ITEMS = NAV_ITEMS.filter((item) => item.id !== 'logs');

function BrandMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="26" height="26" rx="8" stroke="var(--accent-primary)" strokeWidth="2" />
      <circle cx="14" cy="14" r="8.5" stroke="var(--accent-primary)" strokeOpacity="0.45" strokeWidth="1.5" />
      <circle cx="14" cy="14" r="4" fill="var(--accent-primary)" />
    </svg>
  );
}

export function Sidebar({ active, isOpen, onClose }: { active: string, isOpen?: boolean, onClose?: () => void }) {
  const { t } = useTranslation();
  const version = (window as any).APP_VERSION as string | undefined;

  return (
    <>
      <aside className={`app-sidebar ${isOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-brand">
          <BrandMark />
          <span className="sidebar-brand__name">{t('app.title')}</span>
          {isOpen && (
            <button type="button" className="btn-close mobile-only" onClick={onClose} aria-label={t('common.close')} style={{ marginLeft: 'auto' }}>
              <X size={20} />
            </button>
          )}
        </div>

        <nav className="sidebar-nav" aria-label={t('sidebar.navigation')}>
          {NAV_ITEMS.map(({ id, to, icon: Icon, label }) => (
            <Link
              key={id}
              to={to}
              className={`nav-item ${active === id ? 'active' : ''}`}
              aria-current={active === id ? 'page' : undefined}
              onClick={onClose}
            >
              <Icon size={18} aria-hidden="true" /> {t(label)}
            </Link>
          ))}
        </nav>

        {version && <div className="sidebar-footer">GravityLAN v{version}</div>}
      </aside>

      <nav className="mobile-tabbar" aria-label={t('sidebar.navigation')}>
        {TAB_ITEMS.map(({ id, to, icon: Icon, label }) => (
          <Link
            key={id}
            to={to}
            className={`mobile-tabbar__item ${active === id ? 'active' : ''}`}
            aria-current={active === id ? 'page' : undefined}
          >
            <Icon size={20} aria-hidden="true" />
            <span>{t(label)}</span>
          </Link>
        ))}
      </nav>
    </>
  );
}
