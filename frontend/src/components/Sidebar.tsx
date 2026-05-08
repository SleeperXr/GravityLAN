import { LayoutDashboard, Settings, Network, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export function Sidebar({ active, isOpen, onClose }: { active: string, isOpen?: boolean, onClose?: () => void }) {
  const { t } = useTranslation();

  return (
    <aside className={`app-sidebar ${isOpen ? 'mobile-open' : ''}`}>
      <div className="logo">
        <div className="logo__icon">
          <Network size={22} color="white" strokeWidth={2.5} />
        </div>
        <span className="logo__text">{t('app.title')}</span>
        
        {/* Mobile Close Button */}
        <button 
          className="btn-close mobile-only" 
          onClick={onClose}
          style={{ display: isOpen ? 'flex' : 'none' }}
        >
          <X size={20} />
        </button>
      </div>

      <nav style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)' }}>
        <Link 
          to="/" 
          className={`nav-item ${active === 'dashboard' ? 'active' : ''}`}
          onClick={onClose}
        >
          <LayoutDashboard size={18} /> {t('sidebar.dashboard')}
        </Link>
        <Link 
          to="/network" 
          className={`nav-item ${active === 'network' ? 'active' : ''}`}
          onClick={onClose}
        >
          <Network size={18} /> {t('sidebar.network_planner')}
        </Link>
        <Link 
          to="/settings" 
          className={`nav-item ${active === 'settings' ? 'active' : ''}`}
          onClick={onClose}
        >
          <Settings size={18} /> {t('sidebar.settings')}
        </Link>
      </nav>

      <div style={{ marginTop: 'auto', padding: 'var(--space-md)', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
        {t('app.title')} v0.1.0
      </div>
    </aside>
  );
}
