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
        className={`notification-bell ${history.length > 0 && isOpen ? 'notification-bell--active' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
        style={{ 
          background: isOpen ? 'var(--bg-elevated)' : 'var(--bg-secondary)',
          color: history.length > 0 ? 'var(--accent-primary)' : 'var(--text-secondary)'
        }}
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
        <div style={{
          position: 'absolute',
          top: '100%',
          right: 0,
          marginTop: 8,
          width: 320,
          maxHeight: 480,
          background: 'var(--bg-dashboard)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.4)',
          zIndex: 1000,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'slideDown 0.2s ease-out'
        }}>
          <div style={{ 
            padding: '12px 16px', 
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--bg-elevated)'
          }}>
            <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Bell size={16} /> {t('notifications.title')}
            </h3>
            <div style={{ display: 'flex', gap: 4 }}>
              {history.length > 0 && (
                <button 
                  className="btn-icon" 
                  onClick={clearHistory}
                  style={{ color: 'var(--text-tertiary)' }}
                  title={t('notifications.clear_all')}
                >
                  <Trash2 size={14} />
                </button>
              )}
              <button 
                className="btn-close" 
                onClick={() => setIsOpen(false)}
                style={{ width: 24, height: 24 }}
              >
                <X size={14} />
              </button>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
            {history.length === 0 ? (
              <div style={{ 
                padding: '40px 20px', 
                textAlign: 'center', 
                color: 'var(--text-tertiary)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 12
              }}>
                <BellOff size={32} opacity={0.2} />
                <span style={{ fontSize: '0.85rem' }}>{t('notifications.no_notifications')}</span>
              </div>
            ) : (
              history.map((toast) => (
                <div key={toast.id} style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid rgba(255,255,255,0.03)',
                  transition: 'background 0.2s',
                  cursor: 'default'
                }} className="notification-item">
                  <div style={{ display: 'flex', gap: 12 }}>
                    <div style={{ marginTop: 2 }}>
                      {toast.type === 'success' && <CheckCircle size={16} color="#10b981" />}
                      {toast.type === 'error' && <AlertCircle size={16} color="#ef4444" />}
                      {toast.type === 'info' && <Info size={16} color="#38bdf8" />}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ 
                        fontSize: '0.85rem', 
                        fontWeight: 600, 
                        color: 'var(--text-primary)',
                        marginBottom: 2
                      }}>
                        {toast.title}
                      </div>
                      <div style={{ 
                        fontSize: '0.75rem', 
                        color: 'var(--text-secondary)',
                        lineHeight: 1.4,
                        wordBreak: 'break-word'
                      }}>
                        {toast.message}
                      </div>
                      <div style={{ 
                        fontSize: '0.65rem', 
                        color: 'var(--text-tertiary)',
                        marginTop: 6,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4
                      }}>
                        <Clock size={10} />
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
        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .notification-item:hover {
          background: rgba(255,255,255,0.02);
        }
      `}</style>
    </div>
  );
}
