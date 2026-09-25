import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LiveLogs } from './LiveLogs';
import { Sidebar } from '../Sidebar';
import { MobileHeader } from '../MobileHeader';

export function LogsPage() {
  const { t } = useTranslation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <div className="app-layout">
      <Sidebar active="logs" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      <main className="app-main" style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <MobileHeader title={t('sidebar.logs')} onMenuClick={() => setIsSidebarOpen(true)} />
        <header className="desktop-only" style={{ marginBottom: 'var(--space-lg)' }}>
          <h1 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 600 }}>
            {t('settings.live_logs_title') || 'System Live Logs'}
          </h1>
        </header>
        <div style={{ flex: 1, minHeight: 0 }}>
          <LiveLogs />
        </div>
      </main>
    </div>
  );
}
