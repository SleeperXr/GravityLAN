import React, { useState, useEffect } from 'react';
import { Sidebar } from '../Sidebar';
import { MobileHeader } from '../MobileHeader';
import TopologyMap from './TopologyMap';
import RackVisualizer from './RackVisualizer';
import { Network, Layout } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type { Device } from '../../types';

const NetworkPlanner: React.FC = () => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<'topology' | 'rack'>('topology');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [devices, setDevices] = useState<Device[]>([]);

  useEffect(() => {
    // Through the API client (sends the bearer token, rejects error responses): a bare
    // fetch without it got {"detail": ...} back and the rack view crashed on devices.filter
    api.getDevices()
      .then((data) => setDevices(Array.isArray(data) ? data : []))
      .catch(err => console.error('Failed to fetch devices', err));
  }, []);

  return (
    // Use the exact same wrapper as Dashboard — app-layout is a CSS Grid
    <div className="app-layout" style={{ height: '100vh', overflow: 'hidden' }}>
      <Sidebar active="topology" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />

      {/* app-main already has padding + overflow-y:auto — we override those here */}
      <main style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
        padding: '24px',
        background: 'var(--bg-app)',
      }}>
        <MobileHeader title={t('sidebar.topology')} onMenuClick={() => setIsSidebarOpen(true)} />

        {/* Header with the view switch */}
        <header className="planner-header">
          <div className="visually-hidden-mobile">
            <h1 className="page-header__title">{t('sidebar.topology')}</h1>
            <p className="page-header__subtitle">{t('topology.page_subtitle')}</p>
          </div>
          <div className="segmented" role="group" aria-label={t('topology.view_label')}>
            <button
              type="button"
              className="segmented__option segmented__option--icon"
              aria-pressed={activeTab === 'topology'}
              onClick={() => setActiveTab('topology')}
            >
              <Network size={15} aria-hidden="true" /> {t('topology.tab_map')}
            </button>
            <button
              type="button"
              className="segmented__option segmented__option--icon"
              aria-pressed={activeTab === 'rack'}
              onClick={() => setActiveTab('rack')}
            >
              <Layout size={15} aria-hidden="true" /> {t('topology.tab_rack')}
            </button>
          </div>
        </header>

        {/* Content Area — explicit pixel height so ReactFlow gets a non-zero container */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-subtle)',
            overflow: 'hidden',
            background: 'var(--bg-surface)',
          }}
        >
          {activeTab === 'topology' ? (
            <TopologyMap />
          ) : (
            <RackVisualizer devices={devices} />
          )}
        </div>
      </main>
    </div>
  );
};

export default NetworkPlanner;
