import React, { useState, useEffect } from 'react';
import { Server, Layout, RefreshCw } from 'lucide-react';
import { api } from '../../api/client';

interface Device {
  id: number;
  hostname: string;
  display_name: string;
  ip: string;
  status: string;
  rack_id: number | null;
  rack_unit: number | null;
  rack_height: number;
}

interface RackVisualizerProps {
  devices: Device[];
}

const RackVisualizer: React.FC<RackVisualizerProps> = ({ devices }) => {
  const [racks, setRacks] = useState<any[]>([]);
  const [selectedRack, setSelectedRack] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadRacks = async () => {
      try {
        const data = await api.getRacks();
        setRacks(data);
        if (data.length > 0) setSelectedRack(data[0]);
      } catch (err) {
        console.error('Failed to load racks:', err);
      } finally {
        setIsLoading(false);
      }
    };
    loadRacks();
  }, []);

  const createDefaultRack = async () => {
    setIsLoading(true);
    try {
      const data = await api.createRack({ name: 'Main Rack', units: 42, width: 19 });
      setRacks([data]);
      setSelectedRack(data);
    } catch (err) {
      console.error('Failed to create default rack:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // Still loading from API
  if (isLoading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '12px', color: '#94a3b8' }}>
      <RefreshCw size={20} className="animate-spin text-sky-500" />
      <span className="font-bold">Loading Racks...</span>
    </div>
  );

  // Loaded but no racks in DB yet
  if (!selectedRack) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '16px' }}>
      <div style={{ fontSize: '3rem' }}>🗄️</div>
      <p className="text-white font-extrabold text-xl">No Racks Found</p>
      <p className="text-slate-400 text-sm">Create your first rack to start visualizing your infrastructure.</p>
      <button
        onClick={createDefaultRack}
        className="px-6 py-2.5 bg-sky-500 text-black font-black rounded-xl shadow-lg hover:scale-105 transition-all"
      >
        + Create Default Rack (42U)
      </button>
    </div>
  );

  const rackDevices = devices.filter(d => d.rack_id === selectedRack.id);
  const units = Array.from({ length: selectedRack.units }, (_, i) => selectedRack.units - i);

  return (
    <div className="flex flex-col h-full p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-10">
        <div>
          <h2 className="text-3xl font-extrabold text-white flex items-center gap-3">
            <Server size={32} className="text-sky-400" />
            {selectedRack.name}
          </h2>
          <p className="text-slate-400 font-medium ml-11">
            {selectedRack.width}" Standard Rack • {selectedRack.units}U Total
          </p>
        </div>

        <div className="flex gap-3 bg-slate-800/40 p-1.5 rounded-2xl border border-white/5 backdrop-blur-md">
          {racks.map(r => (
            <button
              key={r.id}
              onClick={() => setSelectedRack(r)}
              className={`px-4 py-1.5 rounded-xl text-xs font-bold transition-all duration-300 ${
                selectedRack.id === r.id 
                  ? 'bg-sky-500 text-black shadow-lg shadow-sky-500/20' 
                  : 'text-slate-400 hover:text-white hover:bg-white/5'
              }`}
            >
              {r.name}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-16 flex-1 min-h-0">
        {/* The Rack */}
        <div className="bg-[#0a0a0a] border-[12px] border-slate-800 rounded-3xl p-1.5 w-[450px] relative flex flex-col shadow-[0_30px_60px_-12px_rgba(0,0,0,0.6)] flex-shrink-0">
          {units.map((u) => {
            const device = rackDevices.find(d => d.rack_unit === u);
            
            const isCovered = rackDevices.some(d => 
              d.rack_unit !== null && d.rack_unit > u && (d.rack_unit - (d.rack_height || 1) < u)
            );
            if (isCovered && (!device || device.rack_unit !== u)) return null;

            if (!device || device.rack_unit !== u) {
              return (
                <div key={u} className="h-7 border-b border-white/5 flex items-center px-4 text-[10px] font-mono text-slate-700 relative group hover:bg-white/5 transition-colors">
                  <span className="absolute -left-12 w-8 text-right opacity-50">{u}</span>
                  <div className="w-full h-px bg-white/5"></div>
                </div>
              );
            }

            const height = device.rack_height || 1;
            return (
              <div key={u} 
                style={{ height: `${height * 1.75}rem` }} 
                className="bg-gradient-to-b from-slate-700 to-slate-800 border border-sky-500/40 rounded-lg m-0.5 flex flex-col justify-center px-5 shadow-[inset_0_1px_1px_rgba(255,255,255,0.1),inset_0_0_20px_rgba(0,0,0,0.4)] relative z-10 group hover:border-sky-400 transition-all cursor-default"
              >
                <span className="absolute -left-12 w-8 text-right text-slate-500 font-mono text-[11px] group-hover:text-sky-400 transition-colors font-bold">{u}</span>
                <div className="flex items-center gap-3">
                  <div className={`w-2.5 h-2.5 rounded-full ${device.status === 'online' ? 'bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.6)] animate-pulse' : 'bg-rose-500'}`}></div>
                  <span className="font-black text-sm text-white tracking-tight truncate">{device.display_name || device.hostname}</span>
                </div>
                <div className="text-[10px] text-slate-400 font-bold ml-5 mt-1">
                  {device.ip} • {height}U
                </div>
              </div>
            );
          })}
        </div>

        {/* Legend / Stats */}
        <div className="flex-1 max-w-lg">
          <div className="bg-slate-800/40 backdrop-blur-xl p-8 rounded-3xl border border-white/10 shadow-2xl">
            <h3 className="text-xl font-extrabold text-white mb-6 flex items-center gap-2">
              <Layout size={20} className="text-sky-400" />
              Rack Statistics
            </h3>
            <div className="grid grid-cols-2 gap-6">
              <div className="p-6 bg-slate-900/60 rounded-2xl border border-white/5">
                <div className="text-[10px] text-slate-500 font-black uppercase tracking-widest mb-1">Occupied Units</div>
                <div className="text-3xl font-black text-sky-400">
                  {rackDevices.reduce((acc, d) => acc + (d.rack_height || 1), 0)} <span className="text-lg text-slate-600 font-bold">/ {selectedRack.units}</span>
                </div>
              </div>
              <div className="p-6 bg-slate-900/60 rounded-2xl border border-white/5">
                <div className="text-[10px] text-slate-500 font-black uppercase tracking-widest mb-1">Active Devices</div>
                <div className="text-3xl font-black text-white">{rackDevices.length}</div>
              </div>
            </div>

            <div className="mt-10">
              <h4 className="text-xs text-slate-500 font-black uppercase tracking-widest mb-4">Inventory Overview</h4>
              <div className="space-y-3">
                {rackDevices.sort((a,b) => (b.rack_unit || 0) - (a.rack_unit || 0)).map(d => (
                  <div key={d.id} className="flex justify-between items-center p-3 bg-white/5 rounded-xl border border-white/5 hover:border-white/10 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className={`w-1.5 h-1.5 rounded-full ${d.status === 'online' ? 'bg-emerald-400' : 'bg-rose-500'}`}></div>
                      <span className="text-sm font-bold text-slate-200">{d.display_name || d.hostname}</span>
                    </div>
                    <span className="text-[10px] font-black bg-slate-800 px-2.5 py-1 rounded-lg text-slate-400 uppercase tracking-tighter">U{d.rack_unit} • {d.rack_height}U</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RackVisualizer;
