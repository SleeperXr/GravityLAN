import { useState, useRef, useEffect } from 'react';
import { Bell, BellOff, X, Trash2, CheckCircle, AlertCircle, Info, Clock } from 'lucide-react';
import { useToast } from '../../context/ToastContext';
import { useTranslation } from 'react-i18next';

export function NotificationCenter() {
  const { t } = useTranslation();
  const { history, clearHistory } = useToast();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div style={{ position: 'relative' }} ref={containerRef}>
      <button 
        className={`notification-bell ${history.length > 0 ? 'notification-bell--active' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
        title={t('notifications.title')}
      >
        <Bell size={20} />
        {history.length > 0 && (
          <span className="notification-bell__badge">
            {history.length}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="notification-panel">
          <div className="notification-panel__header">
            <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Bell size={16} /> {t('notifications.title')}
            </h3>
            <div style={{ display: 'flex', gap: 4 }}>
              {history.length > 0 && (
                <button 
                  className="btn-icon btn-icon--danger" 
                  onClick={clearHistory}
                  title={t('notifications.clear_all')}
                >
                  <Trash2 size={16} />
                </button>
              )}
              <button 
                className="btn-icon" 
                onClick={() => setIsOpen(false)}
              >
                <X size={16} />
              </button>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
            {history.length === 0 ? (
              <div style={{ 
                padding: '48px 24px', 
                textAlign: 'center', 
                color: 'var(--text-tertiary)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 16
              }}>
                <div style={{ 
                  width: 64, height: 64, background: 'rgba(255,255,255,0.02)', 
                  borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' 
                }}>
                  <BellOff size={32} opacity={0.3} />
                </div>
                <span style={{ fontSize: '0.875rem' }}>{t('notifications.no_notifications')}</span>
              </div>
            ) : (
              history.map((toast) => (
                <div key={toast.id} className="notification-item" style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid rgba(255,255,255,0.03)',
                  transition: 'background 0.2s',
                  cursor: 'default'
                }}>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <div style={{ marginTop: 2 }}>
                      {toast.type === 'success' && <CheckCircle size={18} color="var(--accent-success)" />}
                      {toast.type === 'error' && <AlertCircle size={18} color="var(--accent-danger)" />}
                      {toast.type === 'info' && <Info size={18} color="var(--accent-primary)" />}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ 
                        fontSize: '0.875rem', 
                        fontWeight: 600, 
                        color: 'var(--text-primary)',
                        marginBottom: 2
                      }}>
                        {toast.title}
                      </div>
                      <div style={{ 
                        fontSize: '0.8rem', 
                        color: 'var(--text-secondary)',
                        lineHeight: 1.5,
                        wordBreak: 'break-word'
                      }}>
                        {toast.message}
                      </div>
                      <div style={{ 
                        fontSize: '0.7rem', 
                        color: 'var(--text-tertiary)',
                        marginTop: 8,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6
                      }}>
                        <Clock size={12} />
                        {toast.timestamp.toLocaleTimeString()}
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <style>{`
        .notification-item:hover {
          background: rgba(255,255,255,0.03);
        }
      `}</style>
    </div>
  );
}
