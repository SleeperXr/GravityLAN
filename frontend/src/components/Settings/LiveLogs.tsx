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

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const wsBase = import.meta.env.DEV ? `${protocol}//${host}:8000` : `${protocol}//${window.location.host}`;
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
      height: '100%',
      minHeight: '450px',
      background: 'rgba(15, 23, 42, 0.4)',
      borderRadius: 'var(--radius-xl)',
      border: '1px solid var(--border-medium)',
      overflow: 'hidden',
      backdropFilter: blur('12px')
    }}>
      <div className="log-header" style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Terminal size={20} className="log-icon" />
          <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, letterSpacing: '0.02em' }}>
            {t('settings.live_logs_title', 'System Live Logs')}
          </h3>
          <div style={{
            width: '10px',
            height: '10px',
            borderRadius: '50%',
            background: isConnected ? 'var(--accent-success)' : 'var(--accent-danger)',
            boxShadow: isConnected ? '0 0 12px var(--accent-success)' : 'none',
            transition: 'all 0.3s ease'
          }} />
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="btn btn-ghost btn-sm"
            title={isPaused ? t('common.resume') : t('common.pause')}
            style={{ padding: '8px' }}
          >
            {isPaused ? <PlayCircle size={18} /> : <StopCircle size={18} />}
          </button>
          <button
            onClick={copyToClipboard}
            className="btn btn-ghost btn-sm"
            title={t('common.copy')}
            style={{ padding: '8px' }}
          >
            <Copy size={18} />
          </button>
          <button
            onClick={clearLogs}
            className="btn btn-ghost btn-sm"
            title={t('common.clear')}
            style={{ padding: '8px', color: 'var(--accent-danger)' }}
          >
            <Trash2 size={18} />
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          background: '#020617',
          color: '#cbd5e1',
          padding: 'var(--space-md)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.825rem',
          overflowY: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          lineHeight: '1.6'
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
