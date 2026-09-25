import { useState } from 'react';
import { Lock, ArrowRight, ShieldCheck, AlertCircle } from 'lucide-react';
import { api } from '../../api/client';
import { motion, AnimatePresence } from 'framer-motion';
import { useTranslation } from 'react-i18next';

interface LoginModalProps {
  onSuccess: () => void;
}

export function LoginModal({ onSuccess }: LoginModalProps) {
  const { t } = useTranslation();
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await api.login(password);
      onSuccess();
    } catch (err: any) {
      setError(err.message || t('auth.invalid_password'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-slate-950/90 backdrop-blur-md">
      <motion.div 
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        className="w-full max-w-md p-8 glass-panel bg-slate-900/50 border-white/10 shadow-2xl relative overflow-hidden"
      >
        <div className="relative text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-slate-800 border border-white/10 mb-6">
            <Lock className="text-sky-400" size={26} />
          </div>

          <h1 className="text-2xl font-semibold text-white mb-2 tracking-tight">
            {t('auth.required')}
          </h1>
          <p className="text-slate-400 text-sm mb-8">
            {t('auth.description')}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <input
                autoFocus
                type="password"
                placeholder={t('auth.password_placeholder')}
                aria-label={t('auth.password_placeholder')}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-slate-950/50 border border-white/10 rounded-xl px-5 py-4 text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50 transition-all placeholder:text-slate-500"
                disabled={loading}
              />
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <ShieldCheck size={18} className={password ? 'text-sky-500/50' : 'text-slate-700'} />
              </div>
            </div>

            <AnimatePresence>
              {error && (
                <motion.div 
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex items-center gap-2 text-rose-400 text-xs bg-rose-500/10 p-3 rounded-lg border border-rose-500/20"
                >
                  <AlertCircle size={14} />
                  <span>{error}</span>
                </motion.div>
              )}
            </AnimatePresence>

            <button
              type="submit"
              disabled={loading || !password}
              className="w-full bg-sky-400 hover:bg-sky-300 disabled:opacity-50 disabled:hover:bg-sky-400 text-slate-950 font-semibold py-4 rounded-xl flex items-center justify-center gap-2 transition-all group"
            >
              {loading ? (
                <div className="w-5 h-5 border-2 border-slate-950/20 border-t-slate-950 rounded-full animate-spin" />
              ) : (
                <>
                  <span>{t('auth.sign_in')}</span>
                  <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" />
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-8 border-t border-white/5">
            <div className="text-xs text-slate-500 font-mono">
              GravityLAN{(window as any).APP_VERSION ? ` v${(window as any).APP_VERSION}` : ''}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
