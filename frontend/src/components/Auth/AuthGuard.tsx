import { useState, useEffect } from 'react';
import { api } from '../../api/client';
import { LoginModal } from './LoginModal';
import { RefreshCw } from 'lucide-react';

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    const checkAuth = async () => {
      const token = localStorage.getItem('gravitylan_token');
      if (!token) {
        setIsAuthenticated(false);
        return;
      }

      try {
        await api.checkAuth(token);
        setIsAuthenticated(true);
      } catch (err) {
        console.error('Auth verification failed:', err);
        localStorage.removeItem('gravitylan_token');
        setIsAuthenticated(false);
      }
    };

    checkAuth();
  }, []);

  if (isAuthenticated === null) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-950 text-white gap-4">
        <RefreshCw className="text-sky-500 animate-spin" size={32} />
        <span className="text-slate-400 font-medium tracking-wide">Verifying credentials...</span>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginModal onSuccess={() => setIsAuthenticated(true)} />;
  }

  return <>{children}</>;
}
