import { LiveLogs } from './LiveLogs';
import { Terminal } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function LogsPage() {
  const { t } = useTranslation();

  return (
    <div style={{
      height: '100vh',
      background: 'var(--bg-app)',
      color: 'var(--text-primary)',
      padding: 'var(--space-lg)',
      display: 'flex',
      flexDirection: 'column'
    }}>
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: 'var(--space-md)', 
        marginBottom: 'var(--space-lg)',
        paddingBottom: 'var(--space-md)',
        borderBottom: '1px solid var(--border-subtle)'
      }}>
        <Terminal size={24} style={{ color: '#38bdf8' }} />
        <h1 style={{ margin: 0, fontSize: '1.5rem', color: '#f8fafc' }}>
          {t('settings.live_logs_title') || 'System Live Logs'}
        </h1>
      </div>
      
      <div style={{ flex: 1, minHeight: 0 }}>
        <LiveLogs />
      </div>

      <div style={{ 
        marginTop: 'var(--space-md)', 
        fontSize: '0.75rem', 
        color: 'var(--text-tertiary)',
        textAlign: 'center'
      }}>
        GravityLAN Backend Live Streaming • {new Date().toLocaleTimeString()}
      </div>
    </div>
  );
}
