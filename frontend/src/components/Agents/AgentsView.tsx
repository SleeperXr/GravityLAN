import { useState, useEffect, useRef } from 'react';
import { Sidebar } from '../Sidebar';
import { MobileHeader } from '../MobileHeader';
import { api } from '../../api/client';
import { 
  Server, 
  Database, 
  Cpu, 
  MemoryStick as Memory, 
  RefreshCw,
  Search,
  Filter,
  TrendingUp,
  Activity,
  ArrowUpRight,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  Clock,
  Thermometer,
  Zap,
  Info,
  HardDrive,
  X,
  LineChart,
  History
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface AgentSummary {
  device_id: number;
  hostname: string;
  ip: string;
  is_online: boolean;
  agent_version: string | null;
  last_seen: string | null;
  cpu_usage: number;
  ram_usage: number;
  temp: number | null;
  uptime_pct: number;
  uptime_history: number[];
  metrics_count: number;
}

interface OverviewData {
  agents: AgentSummary[];
  total_agents: number;
  active_agents: number;
  total_data_points: number;
  avg_cpu: number;
  avg_ram: number;
}

export function AgentsView() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showGlobalMetrics, setShowGlobalMetrics] = useState(false);

  const loadData = async () => {
    try {
      const res = await api.getAgentsOverview();
      setData(res as any);
    } catch (err) {
      console.error('Failed to load agents overview:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  const filteredAgents = data?.agents.filter(a => 
    a.hostname.toLowerCase().includes(search.toLowerCase()) || 
    a.ip.includes(search)
  ) || [];

  return (
    <div className="app-layout">
      <Sidebar active="agents" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      
      <main className="app-main">
        <MobileHeader onMenuClick={() => setIsSidebarOpen(true)} title="Agent Control Center" />
        
        <header className="page-header" style={{ marginBottom: 'var(--space-xl)' }}>
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center w-full gap-4">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <ShieldCheck className="text-sky-500" size={24} />
                <h1 className="text-3xl font-bold text-white tracking-tight">Agent Control Center</h1>
              </div>
              <p className="text-slate-400 text-sm">Managing {data?.total_agents || 0} telemetry nodes across your infrastructure.</p>
            </div>
            <div className="flex gap-3">
              <button className="btn btn-secondary" onClick={loadData} disabled={loading}>
                <RefreshCw size={18} className={loading ? 'spinning' : ''} />
                Sync Agents
              </button>
            </div>
          </div>
        </header>

        {/* Global Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
          <StatCard 
            title="Telemetrie Nodes" 
            value={data?.total_agents || 0} 
            icon={<Server size={20} />} 
            color="sky"
            trend={data?.active_agents || 0}
            trendLabel="active now"
          />
          <StatCard 
            title="System Load (Avg)" 
            value={`${(data?.avg_cpu || 0).toFixed(1)}%`} 
            icon={<Cpu size={20} />} 
            color="amber"
            chartData={[20, 35, 25, 45, 30, 55, (data?.avg_cpu || 0)]}
          />
          <StatCard 
            title="Memory Usage (Avg)" 
            value={`${(data?.avg_ram || 0).toFixed(1)}%`} 
            icon={<Memory size={20} />} 
            color="emerald"
            chartData={[40, 42, 38, 45, 43, 44, (data?.avg_ram || 0)]}
          />
          <StatCard 
            title="Ingested Data" 
            value={(data?.total_data_points || 0).toLocaleString()} 
            icon={<Database size={20} />} 
            color="indigo"
            trendLabel="Total snapshots"
          />
        </div>

        {/* Action Bar */}
        <div className="flex flex-col md:flex-row gap-4 mb-8 items-center justify-between glass-panel p-4 border-white/5">
          <div className="relative w-full md:w-96">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
            <input 
              type="text" 
              className="input w-full h-12 bg-white/5 border-white/10" 
              style={{ paddingLeft: '3rem' }}
              placeholder="Filter by name, IP, or version..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-3 w-full md:w-auto">
             <button className="btn btn-ghost flex-1 md:flex-none">
               <Filter size={18} /> Filter
             </button>
             <button 
              className="btn btn-primary flex-1 md:flex-none px-6"
              onClick={() => setShowGlobalMetrics(true)}
             >
               <Activity size={18} /> Global Analytics
             </button>
          </div>
        </div>

        {/* Agents Master Table */}
        <div className="glass-panel overflow-hidden border border-white/10 shadow-2xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[1000px]">
              <thead>
                <tr className="bg-white/[0.03] text-slate-400 text-xs uppercase tracking-widest font-bold">
                  <th className="px-6 py-5 border-b border-white/5 w-12"></th>
                  <th className="px-6 py-5 border-b border-white/5">Agent Identity</th>
                  <th className="px-6 py-5 border-b border-white/5 text-center">Connection</th>
                  <th className="px-6 py-5 border-b border-white/5">Performance (Live)</th>
                  <th className="px-6 py-5 border-b border-white/5">Uptime History (24h)</th>
                  <th className="px-6 py-5 border-b border-white/5 text-right">Activity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                <AnimatePresence>
                  {filteredAgents.map((agent, i) => (
                    <React.Fragment key={agent.device_id}>
                      <motion.tr 
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        transition={{ delay: i * 0.03 }}
                        className={`hover:bg-white/[0.04] transition-all group cursor-pointer ${expandedId === agent.device_id ? 'bg-white/[0.06]' : ''}`}
                        onClick={() => setExpandedId(expandedId === agent.device_id ? null : agent.device_id)}
                      >
                        <td className="px-6 py-5 text-center">
                          {expandedId === agent.device_id ? <ChevronDown size={20} className="text-sky-400" /> : <ChevronRight size={20} className="text-slate-600 group-hover:text-slate-400" />}
                        </td>
                        <td className="px-6 py-5">
                          <div className="flex items-center gap-4">
                            <div className={`w-12 h-12 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110 ${
                              agent.is_online ? 'bg-sky-500/20 text-sky-400 shadow-lg shadow-sky-500/10' : 'bg-slate-800 text-slate-500'
                            }`}>
                              <Server size={22} />
                            </div>
                            <div>
                              <div className="font-bold text-white text-base group-hover:text-sky-400 transition-colors">{agent.hostname}</div>
                              <div className="text-xs text-slate-500 font-mono mt-0.5 flex items-center gap-2">
                                <span>{agent.ip}</span>
                                <span className="w-1 h-1 rounded-full bg-slate-700"></span>
                                <span className="bg-white/5 px-1.5 py-0.5 rounded">v{agent.agent_version || '0.0.0'}</span>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-5 text-center">
                          <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold tracking-tight ${
                            agent.is_online 
                              ? 'bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20' 
                              : 'bg-rose-500/10 text-rose-400 ring-1 ring-rose-500/20'
                          }`}>
                            <span className={`w-2 h-2 rounded-full ${agent.is_online ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`}></span>
                            {agent.is_online ? 'CONNECTED' : 'DISCONNECTED'}
                          </div>
                        </td>
                        <td className="px-6 py-5">
                          <div className="flex items-center gap-6">
                            <div className="flex-1 space-y-3 min-w-[140px]">
                              <div className="space-y-1">
                                <div className="flex justify-between text-[10px] text-slate-400 uppercase font-bold">
                                  <span>CPU Load</span>
                                  <span>{agent.cpu_usage.toFixed(1)}%</span>
                                </div>
                                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                  <motion.div 
                                    initial={{ width: 0 }}
                                    animate={{ width: `${agent.cpu_usage}%` }}
                                    className="h-full bg-amber-500"
                                  ></motion.div>
                                </div>
                              </div>
                              <div className="space-y-1">
                                <div className="flex justify-between text-[10px] text-slate-400 uppercase font-bold">
                                  <span>Memory</span>
                                  <span>{agent.ram_usage.toFixed(1)}%</span>
                                </div>
                                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                                  <motion.div 
                                    initial={{ width: 0 }}
                                    animate={{ width: `${agent.ram_usage}%` }}
                                    className="h-full bg-emerald-500"
                                  ></motion.div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-5">
                          <div className="flex flex-col gap-2">
                             <div className="flex items-end justify-between">
                               <span className={`text-lg font-bold ${
                                 agent.uptime_pct > 99 ? 'text-sky-400' : 
                                 agent.uptime_pct > 95 ? 'text-emerald-400' :
                                 agent.uptime_pct > 80 ? 'text-amber-400' : 'text-rose-400'
                               }`}>{agent.uptime_pct.toFixed(1)}%</span>
                               <span className="text-[10px] text-slate-500 font-bold mb-1">AVAILABILITY</span>
                             </div>
                             <div className="h-8 w-full">
                                <UptimeSparkline data={agent.uptime_history} color={agent.uptime_pct > 95 ? '#0ea5e9' : '#f59e0b'} />
                             </div>
                          </div>
                        </td>
                        <td className="px-6 py-5 text-right">
                          <div className="text-sm font-bold text-slate-200">
                            {agent.last_seen ? new Date(agent.last_seen).toLocaleTimeString() : 'Never'}
                          </div>
                          <div className="text-[10px] text-slate-500 font-bold uppercase mt-1 flex items-center justify-end gap-1">
                            <TrendingUp size={10} />
                            {agent.last_seen ? new Date(agent.last_seen).toLocaleDateString() : '-'}
                          </div>
                        </td>
                      </motion.tr>
                      
                      {/* Expanded Details Section */}
                      <AnimatePresence>
                        {expandedId === agent.device_id && (
                          <tr>
                            <td colSpan={6} className="p-0 border-b border-white/10 bg-white/[0.02]">
                              <motion.div 
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: 'auto', opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                className="overflow-hidden"
                              >
                                <AgentDetailView deviceId={agent.device_id} />
                              </motion.div>
                            </td>
                          </tr>
                        )}
                      </AnimatePresence>
                    </React.Fragment>
                  ))}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        </div>

        {/* Global Metrics Overlay */}
        <AnimatePresence>
          {showGlobalMetrics && (
            <GlobalMetricsOverlay onClose={() => setShowGlobalMetrics(false)} />
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

function UptimeSparkline({ data, color }: { data: number[], color: string }) {
  if (!data || data.length === 0) return <div className="h-full bg-white/5 rounded"></div>;

  // Fixed coordinate space — no distortion
  const W = 400; const H = 60;
  const PAD_T = 4; const PAD_B = 4;
  const chartH = H - PAD_T - PAD_B;

  const pts = data.map((val, i) => {
    const x = (i / Math.max(data.length - 1, 1)) * W;
    const y = PAD_T + chartH - (Math.min(val, 100) / 100) * chartH;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const lineD = `M ${pts.join(' L ')}`;
  const areaD = `M 0,${H} L ${pts.join(' L ')} L ${W},${H} Z`;
  const gradId = `uptime-grad-${color.replace('#', '')}`;

  return (
    <svg className="w-full h-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${gradId})`} />
      <path d={lineD} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function GlobalMetricsOverlay({ onClose }: { onClose: () => void }) {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.getGlobalMetrics();
        setHistory(res.history);
      } catch (err) {
        console.error('Failed to load global metrics:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xl"
    >
      <motion.div 
        initial={{ scale: 0.95, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95, y: 20 }}
        className="glass-panel w-full max-w-6xl max-h-[90vh] overflow-hidden border-white/10 flex flex-col"
      >
        <div className="p-6 border-b border-white/5 flex justify-between items-center bg-white/[0.02]">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-sky-500/20 text-sky-400 rounded-lg">
              <LineChart size={24} />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white tracking-tight">Infrastructure Global Analytics</h2>
              <p className="text-xs text-slate-500 font-bold uppercase tracking-widest mt-0.5">Real-time aggregate performance (24H)</p>
            </div>
          </div>
          <button className="btn-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {loading ? (
            <div className="h-96 flex flex-col items-center justify-center gap-6">
              <RefreshCw size={48} className="text-sky-500 spinning" />
              <div className="text-center">
                <h3 className="text-lg font-bold text-white mb-1">Aggregating Global Telemetry</h3>
                <p className="text-slate-500 text-sm">Processing snapshots from all active agents...</p>
              </div>
            </div>
          ) : (
            <div className="space-y-10">
              <div className="glass-panel p-8 bg-white/[0.01] border-white/5">
                <div className="flex justify-between items-center mb-8">
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-sky-500"></div>
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Network Load</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-emerald-500"></div>
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Global Memory</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-slate-500">
                     <History size={14} />
                     <span className="text-[10px] font-black uppercase tracking-widest">24 Hour Window</span>
                  </div>
                </div>
                
                <div className="h-80 w-full relative">
                  <div className="absolute inset-0 flex flex-col justify-between pointer-events-none">
                    <div className="border-b border-white/[0.03] w-full"></div>
                    <div className="border-b border-white/[0.03] w-full"></div>
                    <div className="border-b border-white/[0.03] w-full"></div>
                    <div className="border-b border-white/[0.03] w-full"></div>
                  </div>
                  
                  <div className="h-full w-full">
                    <MultiGraph 
                      series={[
                        { data: history.map(h => ({ value: h.avg_cpu, timestamp: h.timestamp })), color: '#0ea5e9', label: 'CPU' },
                        { data: history.map(h => ({ value: h.avg_ram, timestamp: h.timestamp })), color: '#10b981', label: 'RAM' }
                      ]}
                    />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="glass-panel p-6 bg-white/[0.03] border-white/5 flex flex-col gap-4">
                  <div className="text-xs text-slate-500 font-bold uppercase tracking-widest">Peak Ingestion</div>
                  <div className="text-3xl font-black text-white">
                    {Math.max(...history.map(h => h.data_points), 0)} <span className="text-sm text-slate-600">/ 15min</span>
                  </div>
                  <div className="text-[10px] text-sky-400 font-bold flex items-center gap-1">
                    <TrendingUp size={12} /> HIGHEST THROUGHPUT REACHED
                  </div>
                </div>
                <div className="glass-panel p-6 bg-white/[0.03] border-white/5 flex flex-col gap-4">
                  <div className="text-xs text-slate-500 font-bold uppercase tracking-widest">Avg CPU Load</div>
                  <div className="text-3xl font-black text-amber-400">
                    {(history.reduce((a, b) => a + b.avg_cpu, 0) / (history.length || 1)).toFixed(1)}%
                  </div>
                  <div className="text-[10px] text-slate-500 font-bold">NETWORK-WIDE SYSTEM HEALTH</div>
                </div>
                <div className="glass-panel p-6 bg-white/[0.03] border-white/5 flex flex-col gap-4">
                  <div className="text-xs text-slate-500 font-bold uppercase tracking-widest">Aggregate Memory</div>
                  <div className="text-3xl font-black text-emerald-400">
                    {(history.reduce((a, b) => a + b.avg_ram, 0) / (history.length || 1)).toFixed(1)}%
                  </div>
                  <div className="text-[10px] text-slate-500 font-bold">TOTAL RAM CONSUMPTION</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

function MultiGraph({ series }: { series: { data: any[], color: string, label: string }[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (!series[0]?.data.length) return null;

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = x / rect.width;
    const index = Math.round(pct * (series[0].data.length - 1));
    setHoverIdx(index);
  };

  return (
    <div 
      className="relative h-full w-full group cursor-crosshair"
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setHoverIdx(null)}
    >
      <svg className="w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        {series.map((s, idx) => {
          const points = s.data.map((d, i) => {
            const x = (i / (s.data.length - 1)) * 100;
            const y = 100 - d.value;
            return `${x},${y}`;
          }).join(' ');
          
          return (
            <React.Fragment key={idx}>
              <defs>
                <linearGradient id={`grad-global-${idx}`} x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor={s.color} stopOpacity="0.1" />
                  <stop offset="100%" stopColor={s.color} stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d={`M 0,100 L ${points} L 100,100 Z`} fill={`url(#grad-global-${idx})`} />
              <motion.path 
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                d={`M ${points}`} 
                fill="none" 
                stroke={s.color} 
                strokeWidth="2" 
                strokeLinecap="round" 
              />
            </React.Fragment>
          );
        })}

        {hoverIdx !== null && series[0].data[hoverIdx] && (
          <line 
            x1={(hoverIdx / (series[0].data.length - 1)) * 100} 
            y1="0" 
            x2={(hoverIdx / (series[0].data.length - 1)) * 100} 
            y2="100" 
            stroke="white" 
            strokeOpacity="0.2" 
            strokeWidth="0.5" 
          />
        )}
      </svg>

      {/* Global Tooltip */}
      {hoverIdx !== null && series[0].data[hoverIdx] && (
        <div 
          className="absolute z-[110] bg-slate-900 border border-white/20 p-3 rounded-lg shadow-2xl pointer-events-none min-w-[120px]"
          style={{ 
            left: `${Math.min((hoverIdx / (series[0].data.length - 1)) * 100, 80)}%`, 
            top: '0%',
            transform: 'translateY(-110%)'
          }}
        >
          <div className="text-[10px] text-slate-500 font-bold uppercase tracking-widest mb-2 border-b border-white/5 pb-1">
            {new Date(series[0].data[hoverIdx].timestamp).toLocaleString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
          {series.map((s, i) => (
            <div key={i} className="flex justify-between gap-4 items-center">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">{s.label}</span>
              <span className="text-sm font-black" style={{ color: s.color }}>{s.data[hoverIdx].value.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentDetailView({ deviceId }: { deviceId: number }) {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await api.getAgentMetrics(deviceId, 60);
        setHistory(res.snapshots);
      } catch (err) {
        console.error('Failed to fetch history:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, [deviceId]);

  if (loading) {
    return (
      <div className="p-12 flex flex-col items-center justify-center gap-4">
        <RefreshCw size={32} className="text-sky-500 spinning" />
        <span className="text-slate-400 font-medium">Analyzing historical telemetry...</span>
      </div>
    );
  }

  const latest = history[history.length - 1];

  return (
    <div className="p-8 space-y-8">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="glass-panel p-6 bg-white/[0.03] border-white/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-amber-500/20 text-amber-400 rounded-lg">
              <Cpu size={20} />
            </div>
            <div>
              <h4 className="font-bold text-white uppercase text-xs tracking-widest">CPU History</h4>
              <p className="text-[10px] text-slate-500">Utilization Trend (60 Snapshots)</p>
            </div>
          </div>
          <div className="h-48 w-full">
            <DetailGraph 
              data={history.map(h => ({ value: h.cpu_percent, timestamp: h.timestamp }))} 
              color="#f59e0b" 
              label="CPU" 
              suffix="%"
            />
          </div>
        </div>

        <div className="glass-panel p-6 bg-white/[0.03] border-white/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-emerald-500/20 text-emerald-400 rounded-lg">
              <Memory size={20} />
            </div>
            <div>
              <h4 className="font-bold text-white uppercase text-xs tracking-widest">Memory History</h4>
              <p className="text-[10px] text-slate-500">RAM Usage Pattern</p>
            </div>
          </div>
          <div className="h-48 w-full">
            <DetailGraph 
              data={history.map(h => ({ value: h.ram.percent, timestamp: h.timestamp }))} 
              color="#10b981" 
              label="RAM" 
              suffix="%"
            />
          </div>
        </div>

        <div className="glass-panel p-6 bg-white/[0.03] border-white/5">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-indigo-500/20 text-indigo-400 rounded-lg">
              <Thermometer size={20} />
            </div>
            <div>
              <h4 className="font-bold text-white uppercase text-xs tracking-widest">Thermal Stats</h4>
              <p className="text-[10px] text-slate-500">Core Temperature (°C)</p>
            </div>
          </div>
          <div className="h-48 w-full">
            <DetailGraph 
              data={history.map(h => ({ value: h.temperature || 0, timestamp: h.timestamp }))} 
              color="#818cf8" 
              label="TEMP" 
              suffix="°C"
              max={100} 
            />
          </div>
        </div>
      </div>

      <div className="glass-panel p-6 bg-white/[0.01] border-white/5">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-sky-500/20 text-sky-400 rounded-lg">
            <HardDrive size={20} />
          </div>
          <h4 className="font-bold text-white uppercase text-xs tracking-widest">Monitored Storage</h4>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {latest?.disk?.map((disk: any) => (
            <div key={disk.path} className="p-4 bg-white/5 border border-white/5 rounded-xl hover:bg-white/[0.08] transition-colors group">
              <div className="flex justify-between items-start mb-3">
                <div className="flex flex-col cursor-pointer group/path" 
                  title="Click to copy full path"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(disk.path);
                    const target = e.currentTarget;
                    const originalText = target.innerText;
                    target.innerHTML = '<span class="text-sky-400 text-[10px] uppercase font-bold">Copied!</span>';
                    setTimeout(() => { target.innerText = originalText; }, 1000);
                  }}
                >
                  <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider mb-1">Mount Point</span>
                  <span className="text-white font-bold truncate" title={disk.path}>{disk.path}</span>
                </div>
                <div className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                  disk.percent > 90 ? 'bg-rose-500/20 text-rose-400' : 
                  disk.percent > 75 ? 'bg-amber-500/20 text-amber-400' : 'bg-emerald-500/20 text-emerald-400'
                }`}>
                  {disk.percent.toFixed(0)}%
                </div>
              </div>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden mb-3">
                <div className="h-full bg-sky-500 rounded-full" style={{ width: `${disk.percent}%` }}></div>
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-bold">
                <span>{disk.used_gb.toFixed(1)} GB USED</span>
                <span>{disk.total_gb.toFixed(1)} GB TOTAL</span>
              </div>
            </div>
          ))}
          {!latest?.disk?.length && (
             <div className="col-span-full py-8 text-center text-slate-600 text-sm">No disk usage reported by agent.</div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-4 mt-2">
         <div className="flex-1 min-w-[200px] bg-white/[0.02] border border-white/5 p-4 rounded-xl flex items-center justify-between">
           <div className="flex items-center gap-3">
             <Clock className="text-slate-500" size={18} />
             <span className="text-xs text-slate-400 font-bold uppercase tracking-wider">Interval</span>
           </div>
           <span className="text-lg font-bold text-white">30s</span>
         </div>
         <div className="flex-1 min-w-[200px] bg-white/[0.02] border border-white/5 p-4 rounded-xl flex items-center justify-between">
           <div className="flex items-center gap-3">
             <Zap className="text-amber-500" size={18} />
             <span className="text-xs text-slate-400 font-bold uppercase tracking-wider">Status</span>
           </div>
           <span className="text-lg font-bold text-emerald-400">OPTIMAL</span>
         </div>
         <div className="flex-1 min-w-[200px] bg-white/[0.02] border border-white/5 p-4 rounded-xl flex items-center justify-between">
           <div className="flex items-center gap-3">
             <Info className="text-sky-500" size={18} />
             <span className="text-xs text-slate-400 font-bold uppercase tracking-wider">First Seen</span>
           </div>
           <span className="text-sm font-medium text-slate-300">
             {history.length > 0 ? new Date(history[0].timestamp).toLocaleString() : 'N/A'}
           </span>
         </div>
      </div>
    </div>
  );
}

function DetailGraph({ data, color, label, suffix, max = 100 }: {
  data: { value: number; timestamp: string }[];
  color: string;
  label: string;
  suffix: string;
  max?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-600 text-xs">
        No history data
      </div>
    );
  }

  // Fixed SVG coordinate space — prevents aspect-ratio distortion
  const W = 600;
  const H = 160;
  const PAD_L = 38; // space for Y-axis labels
  const PAD_R = 10;
  const PAD_T = 10;
  const PAD_B = 24; // space for X-axis labels
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const vals = data.map(d => d.value);
  const dataMin = Math.min(...vals);
  const dataMax = Math.max(...vals);
  const dataAvg = vals.reduce((a, b) => a + b, 0) / vals.length;

  // Map value → Y pixel (with 5% top/bottom padding so the line never hits the edge)
  const MARGIN = 0.05;
  const mapY = (v: number) =>
    PAD_T + chartH - ((Math.min(v, max) / max) * (1 - 2 * MARGIN) + MARGIN) * chartH;

  const mapX = (i: number) => PAD_L + (i / Math.max(data.length - 1, 1)) * chartW;

  const pts = data.map((d, i) => `${mapX(i).toFixed(1)},${mapY(d.value).toFixed(1)}`);
  const lineD = `M ${pts.join(' L ')}`;
  const areaD = `M ${PAD_L},${PAD_T + chartH} L ${pts.join(' L ')} L ${PAD_L + chartW},${PAD_T + chartH} Z`;

  const gradId = `dg-grad-${label}`;
  const clipId = `dg-clip-${label}`;

  const yTicks = [0, 25, 50, 75, 100].filter(t => t <= max);

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    // Account for PAD_L as a fraction of total rendered width
    const relX = (e.clientX - rect.left - (PAD_L / W) * rect.width);
    const usableW = (chartW / W) * rect.width;
    const pct = Math.max(0, Math.min(1, relX / usableW));
    setHoverIdx(Math.round(pct * (data.length - 1)));
  };

  const hov = hoverIdx !== null ? data[hoverIdx] : null;

  return (
    <div className="relative w-full h-full flex flex-col gap-2">
      {/* Stats pill row */}
      <div className="flex gap-3 text-[10px] font-bold uppercase tracking-widest">
        <span className="px-2 py-0.5 rounded" style={{ background: `${color}18`, color }}>
          MIN {dataMin.toFixed(1)}{suffix}
        </span>
        <span className="px-2 py-0.5 rounded bg-white/5 text-slate-400">
          AVG {dataAvg.toFixed(1)}{suffix}
        </span>
        <span className="px-2 py-0.5 rounded" style={{ background: `${color}18`, color }}>
          MAX {dataMax.toFixed(1)}{suffix}
        </span>
      </div>

      {/* SVG chart — proper fixed coordinate viewport */}
      <div
        ref={containerRef}
        className="relative flex-1 cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        <svg
          className="w-full h-full"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"  stopColor={color} stopOpacity="0.5" />
              <stop offset="70%" stopColor={color} stopOpacity="0.08" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
            <clipPath id={clipId}>
              <rect x={PAD_L} y={PAD_T} width={chartW} height={chartH} />
            </clipPath>
          </defs>

          {/* Y-axis ticks + grid lines */}
          {yTicks.map(tick => {
            const y = mapY(tick);
            return (
              <React.Fragment key={tick}>
                <line
                  x1={PAD_L} y1={y} x2={PAD_L + chartW} y2={y}
                  stroke="white" strokeOpacity={tick === 0 ? 0.12 : 0.05} strokeWidth="1"
                  strokeDasharray={tick === 0 ? 'none' : '4,4'}
                />
                <text
                  x={PAD_L - 6} y={y + 4}
                  textAnchor="end"
                  fontSize={9}
                  fill="rgba(148,163,184,0.6)"
                  fontFamily="monospace"
                >
                  {tick}
                </text>
              </React.Fragment>
            );
          })}

          {/* AVG line */}
          <line
            x1={PAD_L} y1={mapY(dataAvg)}
            x2={PAD_L + chartW} y2={mapY(dataAvg)}
            stroke={color} strokeOpacity="0.25" strokeWidth="1"
            strokeDasharray="6,4"
            clipPath={`url(#${clipId})`}
          />

          {/* Area fill */}
          <path d={areaD} fill={`url(#${gradId})`} clipPath={`url(#${clipId})`} />

          {/* Line */}
          <motion.path
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            d={lineD}
            fill="none"
            stroke={color}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            clipPath={`url(#${clipId})`}
          />

          {/* X-axis labels: first and last timestamp */}
          <text x={PAD_L} y={H - 6} fontSize={9} fill="rgba(100,116,139,0.7)" fontFamily="monospace">
            {new Date(data[0].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </text>
          <text x={PAD_L + chartW} y={H - 6} fontSize={9} fill="rgba(100,116,139,0.7)" fontFamily="monospace" textAnchor="end">
            {new Date(data[data.length - 1].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </text>

          {/* Hover crosshair */}
          {hov && hoverIdx !== null && (
            <>
              <line
                x1={mapX(hoverIdx)} y1={PAD_T}
                x2={mapX(hoverIdx)} y2={PAD_T + chartH}
                stroke="white" strokeOpacity="0.35" strokeWidth="1"
                strokeDasharray="3,3"
              />
              <circle
                cx={mapX(hoverIdx)} cy={mapY(hov.value)}
                r="5" fill={color} stroke="white" strokeWidth="2"
              />
            </>
          )}
        </svg>

        {/* Floating tooltip */}
        {hov && hoverIdx !== null && (
          <div
            className="absolute z-50 pointer-events-none"
            style={{
              left: `${Math.min((mapX(hoverIdx) / W) * 100, 72)}%`,
              top: `${((mapY(hov.value) - PAD_T) / H) * 100}%`,
              transform: 'translate(12px, -50%)'
            }}
          >
            <div className="bg-slate-900/95 border border-white/20 backdrop-blur-sm px-3 py-2 rounded-lg shadow-2xl">
              <div className="text-[9px] text-slate-500 font-bold uppercase tracking-widest mb-0.5">
                {new Date(hov.timestamp).toLocaleTimeString()}
              </div>
              <div className="text-base font-black" style={{ color }}>
                {hov.value.toFixed(1)}{suffix}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ title, value, icon, color, trend, trendLabel, chartData }: any) {
  const colorMap: any = {
    sky: 'from-sky-500/20 to-sky-500/5 text-sky-400 border-sky-500/20',
    amber: 'from-amber-500/20 to-amber-500/5 text-amber-400 border-amber-500/20',
    emerald: 'from-emerald-500/20 to-emerald-500/5 text-emerald-400 border-emerald-500/20',
    indigo: 'from-indigo-500/20 to-indigo-500/5 text-indigo-400 border-indigo-500/20',
  };

  return (
    <div className={`glass-panel p-6 border bg-gradient-to-br ${colorMap[color]} relative group overflow-hidden`}>
      <div className="flex justify-between items-start mb-4">
        <div className={`p-3 rounded-2xl bg-white/5 border border-white/10 transition-transform group-hover:scale-110`}>
          {icon}
        </div>
        {trend !== undefined && (
          <div className="flex items-center gap-1 text-[10px] font-black uppercase tracking-tighter bg-white/10 px-2 py-1 rounded-lg">
            <ArrowUpRight size={12} />
            {trend} {trendLabel}
          </div>
        )}
      </div>
      
      <div className="flex flex-col">
        <span className="text-slate-400 text-xs font-black uppercase tracking-widest mb-1">{title}</span>
        <div className="text-4xl font-black text-white tracking-tight">{value}</div>
        
        {chartData && (
          <div className="mt-4 h-12 w-full opacity-50">
            <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 20">
              <path 
                d={`M 0 20 ${chartData.map((v: number, i: number) => `L ${i * (100 / (chartData.length - 1))} ${20 - (v / 100) * 20}`).join(' ')} L 100 20 Z`}
                fill="currentColor"
                fillOpacity="0.1"
              />
              <path 
                d={`M 0 ${20 - (chartData[0] / 100) * 20} ${chartData.map((v: number, i: number) => `L ${i * (100 / (chartData.length - 1))} ${20 - (v / 100) * 20}`).join(' ')}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              />
            </svg>
          </div>
        )}
        {trendLabel && !trend && (
           <span className="text-[10px] text-slate-500 font-bold uppercase mt-2 tracking-widest">{trendLabel}</span>
        )}
      </div>
    </div>
  );
}

import React from 'react';
