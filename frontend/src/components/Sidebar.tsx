import { LayoutDashboard, Settings, Network, X, Grid, Server } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import logo from '../assets/logo.svg';

export function Sidebar({ active, isOpen, onClose }: { active: string, isOpen?: boolean, onClose?: () => void }) {
  const { t } = useTranslation();

  return (
    <aside className={`app-sidebar ${isOpen ? 'mobile-open' : ''}`}>
      <div className="logo">
        <div className="logo__icon">
          <img src={logo} alt="Logo" style={{ width: '28px', height: '28px' }} />
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

      <nav style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
        <div className="nav-group">
          <div className="nav-group__label" style={{ fontSize: '0.65rem', fontWeight: 800, color: 'var(--text-tertiary)', padding: '0 var(--space-md)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Main
          </div>
          <Link 
            to="/" 
            className={`nav-item ${active === 'dashboard' ? 'active' : ''}`}
            onClick={onClose}
          >
            <LayoutDashboard size={18} /> {t('sidebar.dashboard')}
          </Link>
        </div>

        <div className="nav-group">
          <div className="nav-group__label" style={{ fontSize: '0.65rem', fontWeight: 800, color: 'var(--text-tertiary)', padding: '0 var(--space-md)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Network
          </div>
          <Link 
            to="/network" 
            className={`nav-item ${active === 'network' ? 'active' : ''}`}
            onClick={onClose}
          >
            <Grid size={18} /> IP Management
          </Link>
          <Link 
            to="/topology" 
            className={`nav-item ${active === 'topology' ? 'active' : ''}`}
            onClick={onClose}
          >
            <Network size={18} /> Network Planner
          </Link>
        </div>

        <div className="nav-group">
          <div className="nav-group__label" style={{ fontSize: '0.65rem', fontWeight: 800, color: 'var(--text-tertiary)', padding: '0 var(--space-md)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            System
          </div>
          <Link 
            to="/agents" 
            className={`nav-item ${active === 'agents' ? 'active' : ''}`}
            onClick={onClose}
          >
            <Server size={18} /> Agents
          </Link>
          <Link 
            to="/settings" 
            className={`nav-item ${active === 'settings' ? 'active' : ''}`}
            onClick={onClose}
          >
            <Settings size={18} /> {t('sidebar.settings')}
          </Link>
        </div>
      </nav>

      <div style={{ marginTop: 'auto', padding: 'var(--space-md)', fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
        {t('app.title')} v0.2.0
      </div>
    </aside>
  );
}
