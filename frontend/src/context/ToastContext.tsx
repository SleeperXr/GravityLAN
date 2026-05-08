import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';

type ToastType = 'success' | 'error' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message: string;
  timestamp: Date;
}

interface ToastContextType {
  showToast: (type: ToastType, title: string, message: string) => void;
  toasts: Toast[];
  history: Toast[];
  clearHistory: () => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [history, setHistory] = useState<Toast[]>([]);

  const showToast = useCallback((type: ToastType, title: string, message: string) => {
    const id = Math.random().toString(36).substr(2, 9);
    const newToast = { id, type, title, message, timestamp: new Date() };
    
    setToasts((prev) => [...prev, newToast]);
    setHistory((prev) => [newToast, ...prev].slice(0, 50)); // Keep last 50
    
    // Auto remove: 15s for errors, 5s for others
    const duration = type === 'error' ? 15000 : 5000;
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, duration);
  }, []);

  const clearHistory = useCallback(() => setHistory([]), []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ showToast, toasts, history, clearHistory, removeToast }}>
      {children}
      <div className="toast-container">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.type}`}>
            <div className="toast__icon">
              {toast.type === 'success' && <CheckCircle size={20} color="var(--accent-success)" />}
              {toast.type === 'error' && <AlertCircle size={20} color="var(--accent-danger)" />}
              {toast.type === 'info' && <Info size={20} color="var(--accent-primary)" />}
            </div>
            <div className="toast__content">
              <div className="toast__title">{toast.title}</div>
              <div className="toast__message">{toast.message}</div>
            </div>
            <button 
              className="btn-icon" 
              onClick={() => removeToast(toast.id)}
              style={{ padding: '4px', opacity: 0.5 }}
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}
