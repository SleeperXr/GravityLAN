import { useState, useEffect, useRef } from 'react';
import { Terminal, Copy, Trash2, StopCircle, PlayCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * LiveLogs component - Streams backend logs via WebSocket.
 */
export function LiveLogs() {
  const { t } = useTranslation();
  const [logs, setLogs] = useState<string[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (isPaused) {
      wsRef.current?.close();
      setIsConnected(false);
      return;
    }

    const host = window.location.hostname;
    const wsBase = import.meta.env.DEV ? `ws://${host}:8000` : `ws://${window.location.host}`;
    const ws = new WebSocket(`${wsBase}/api/logs/ws`);
    wsRef.current = ws;

    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);
    ws.onmessage = (event) => {
      setLogs((prev) => {
        const newLogs = [...prev, event.data];
        return newLogs.slice(-500); // Keep last 500 lines
      });
    };

    return () => {
      ws.close();
    };
  }, [isPaused]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current && !isPaused) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, isPaused]);

  const copyToClipboard = () => {
    const text = logs.join('\n');
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text);
    } else {
      // Fallback for non-secure contexts (HTTP)
      const textArea = document.createElement("textarea");
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
      } catch (err) {
        console.error('Copy fallback failed', err);
      }
      document.body.removeChild(textArea);
    }
  };

  const clearLogs = () => setLogs([]);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '12px',
      height: '100%',
      minHeight: '400px'
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Terminal size={18} className="text-secondary" />
          <h3 style={{ margin: 0, fontSize: '1rem' }}>{t('settings.live_logs_title', 'System Live Logs')}</h3>
          <div style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: isConnected ? '#10b981' : '#ef4444',
            boxShadow: isConnected ? '0 0 8px #10b981' : 'none'
          }} />
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="btn-ghost"
            title={isPaused ? t('common.resume') : t('common.pause')}
            style={{ padding: '6px' }}
          >
            {isPaused ? <PlayCircle size={18} /> : <StopCircle size={18} />}
          </button>
          <button
            onClick={copyToClipboard}
            className="btn-ghost"
            title={t('common.copy')}
            style={{ padding: '6px' }}
          >
            <Copy size={18} />
          </button>
          <button
            onClick={clearLogs}
            className="btn-ghost"
            title={t('common.clear')}
            style={{ padding: '6px', color: 'var(--text-danger)' }}
          >
            <Trash2 size={18} />
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          background: '#0a0a0a',
          color: '#d1d1d1',
          padding: '12px',
          borderRadius: '8px',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8rem',
          overflowY: 'auto',
          border: '1px solid var(--border-subtle)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          lineHeight: '1.4'
        }}
      >
        {logs.length === 0 ? (
          <div style={{ color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
            Waiting for logs...
          </div>
        ) : (
          logs.map((log, i) => (
            <div key={i} style={{ 
              borderBottom: '1px solid rgba(255,255,255,0.05)', 
              padding: '2px 0',
              color: log.includes('[ERROR]') ? '#ef4444' : 
                     log.includes('[WARNING]') ? '#f59e0b' : 
                     log.includes('[INFO]') ? '#3b82f6' : 'inherit'
            }}>
              {log}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
