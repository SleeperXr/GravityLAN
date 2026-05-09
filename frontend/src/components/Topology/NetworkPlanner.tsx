import React, { useState, useEffect } from 'react';
import { Sidebar } from '../Sidebar';
import { MobileHeader } from '../MobileHeader';
import TopologyMap from './TopologyMap';
import RackVisualizer from './RackVisualizer';
import { Network, Layout } from 'lucide-react';

const NetworkPlanner: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'topology' | 'rack'>('topology');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [devices, setDevices] = useState([]);

  useEffect(() => {
    fetch('/api/devices')
      .then(r => r.json())
      .then(setDevices)
      .catch(err => console.error('Failed to fetch devices', err));
  }, []);

  return (
    // Use the exact same wrapper as Dashboard — app-layout is a CSS Grid
    <div className="app-layout" style={{ height: '100vh', overflow: 'hidden' }}>
      <Sidebar active="topology" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />

      {/* app-main already has padding + overflow-y:auto — we override those here */}
      <main style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        overflow: 'hidden',
        padding: '24px',
        background: 'var(--bg-app)',
      }}>
        <MobileHeader title="Network Planner" onMenuClick={() => setIsSidebarOpen(true)} />

        {/* Header */}
        <div style={{ marginBottom: '24px', flexShrink: 0 }}>
          <h1 className="text-4xl font-extrabold text-white tracking-tight mb-1">
            Network Planner
          </h1>
          <p className="text-slate-400 text-base">
            Design and visualize your infrastructure topology
          </p>
        </div>

        {/* Tab Switcher */}
        <div
          className="flex gap-2 bg-slate-800/50 border border-white/5 rounded-2xl p-1.5 w-fit"
          style={{ marginBottom: '20px', flexShrink: 0 }}
        >
          <button
            onClick={() => setActiveTab('topology')}
            className={`flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-bold transition-all duration-200 ${
              activeTab === 'topology'
                ? 'bg-sky-500 text-black shadow-lg shadow-sky-500/30 scale-105'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Network size={16} />
            Topology Map
          </button>
          <button
            onClick={() => setActiveTab('rack')}
            className={`flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-bold transition-all duration-200 ${
              activeTab === 'rack'
                ? 'bg-sky-500 text-black shadow-lg shadow-sky-500/30 scale-105'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Layout size={16} />
            Rack View
          </button>
        </div>

        {/* Content Area — explicit pixel height so ReactFlow gets a non-zero container */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            borderRadius: '20px',
            border: '1px solid rgba(255,255,255,0.06)',
            overflow: 'hidden',
            background: 'rgba(15,23,42,0.6)',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.05)',
          }}
        >
          {activeTab === 'topology' ? (
            <TopologyMap />
          ) : (
            <RackVisualizer devices={devices} />
          )}
        </div>
      </main>
    </div>
  );
};

export default NetworkPlanner;
