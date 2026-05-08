import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { api } from './api/client';
import { SetupWizard } from './components/Setup/SetupWizard';
import { Dashboard } from './components/Dashboard/Dashboard';
import { SubnetView } from './components/Network/SubnetView';
import { SettingsView } from './components/Settings/SettingsView';
import { LogsPage } from './components/Settings/LogsPage';
import { ThemeManager } from './components/ThemeManager';
import { ToastProvider } from './context/ToastContext';

import { NetworkProvider } from './context/NetworkContext';

function App() {
  const [isSetupComplete, setIsSetupComplete] = useState<boolean | null>(null);

  useEffect(() => {
    const checkSetup = async () => {
      try {
        console.log('Checking setup status...');
        const status = await api.getSetupStatus();
        console.log('Setup status response:', status);
        setIsSetupComplete(status.is_setup_complete);
      } catch (err) {
        console.error('Failed to check setup status:', err);
        // Fallback to setup if API fails or returns error
        setIsSetupComplete(false);
      }
    };
    checkSetup();
  }, []);

  if (isSetupComplete === null) {
    return (
      <div style={{ 
        height: '100vh', 
        display: 'flex', 
        flexDirection: 'column',
        alignItems: 'center', 
        justifyContent: 'center',
        background: '#0f172a',
        color: 'white',
        fontFamily: 'sans-serif'
      }}>
        <div style={{ marginBottom: '20px', fontSize: '1.2rem', fontWeight: 'bold' }}>GravityLAN</div>
        <div className="spinning" style={{ marginBottom: '10px' }}>⏳</div>
        <div>Initialisierung...</div>
        <div style={{ marginTop: '20px', fontSize: '0.7rem', color: '#475569' }}>
          Prüfe Setup-Status auf {window.location.origin}...
        </div>
      </div>
    );
  }

  return (
    <ToastProvider>
      <NetworkProvider>
        <BrowserRouter>
          <ThemeManager />
          <Routes>
            {/* Setup Route */}
            {!isSetupComplete && (
              <Route path="*" element={<SetupWizard onComplete={() => setIsSetupComplete(true)} />} />
            )}

            {/* Dashboard Routes */}
            {isSetupComplete && (
              <>
                <Route path="/" element={<Dashboard />} />
                <Route path="/network" element={<SubnetView />} />
                <Route path="/settings" element={<SettingsView />} />
                <Route path="/logs" element={<LogsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </>
            )}
          </Routes>
        </BrowserRouter>
      </NetworkProvider>
    </ToastProvider>
  );
}

export default App;
