import React, { useCallback, useEffect, useState, useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  MarkerType,
  Connection,
  Handle,
  Position,
  NodeProps,
  EdgeProps,
  getBezierPath,
  EdgeLabelRenderer,
  Node,
  Edge,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Share2, Trash2, Server, Activity, Cpu, RefreshCw, Settings, X, Save, Layers, Wifi, Radio, Smartphone, Box, Monitor, Sliders, Wind, Zap, Maximize, Minimize, ChevronUp, ChevronDown } from 'lucide-react';
import { api } from '../../api/client';

// --- Context for Flow Settings ---
const FlowSettingsContext = React.createContext({
  speed: 1.0,
  intensity: 3,
});

// --- Custom Node Component ---
const DeviceNode = React.memo(({ data, selected }: NodeProps) => {
  const isOnline = data.is_online;
  const metrics = data.metrics;
  const hasAgent = data.has_agent;
  
  // Handle configuration from topology_config
  const config = useMemo(() => {
    try {
      return data.topology_config ? JSON.parse(data.topology_config) : {};
    } catch {
      return {};
    }
  }, [data.topology_config]);

  const topHandleType = config.top_handle_type || 'target';
  const bottomHandleType = config.bottom_handle_type || 'source';

  return (
    <div className={`topology-node ${isOnline ? 'online' : 'offline'} ${selected ? 'selected' : ''}`}>
      <div className="node-header">
        <div className="node-icon-container">
          {data.is_ap ? (
            <Radio size={18} className="node-icon text-amber-400" />
          ) : data.virtual_type === 'docker' ? (
            <Box size={18} className="node-icon text-purple-400" />
          ) : data.virtual_type === 'vm' ? (
            <Monitor size={18} className="node-icon text-fuchsia-400" />
          ) : data.is_wlan ? (
            <Smartphone size={18} className="node-icon text-sky-400" />
          ) : (
            <Server size={18} className="node-icon" />
          )}
          <div className={`status-indicator ${isOnline ? 'active' : 'inactive'}`} />
          {data.is_wlan && <Wifi size={10} className="wlan-badge" />}
        </div>
        <div className="node-title-area">
          <div className="node-label">{data.label}</div>
          <div className="node-sublabel">{data.ip}</div>
        </div>
        <div className="node-actions">
           {data.is_host && (
             <div className="host-badge" title="Physical Host System">
               <Server size={10} />
               <span>HOST</span>
             </div>
           )}
           {data.has_agent && <Activity size={12} className="text-sky-400" />}
        </div>
      </div>

      {data.parent_name && (
        <div className="node-parent-info">
          <Layers size={10} />
          <span>On: {data.parent_name}</span>
        </div>
      )}

      {data.is_wlan && data.nearest_ap && (
        <div className="wlan-signals" style={{
          position: 'absolute',
          ...(() => {
            const dx = data.nearest_ap.x - data.x;
            const dy = data.nearest_ap.y - data.y;
            const w = 240;
            const h = 100;
            if (Math.abs(dx) * h > Math.abs(dy) * w) {
              return dx > 0 ? { right: -15, top: '50%', transform: 'translateY(-50%)' } 
                            : { left: -15, top: '50%', transform: 'translateY(-50%)' };
            } else {
              return dy > 0 ? { bottom: -15, left: '50%', transform: 'translateX(-50%)' }
                            : { top: -15, left: '50%', transform: 'translateX(-50%)' };
            }
          })(),
          display: 'flex',
          gap: '2px',
          alignItems: 'flex-end',
          height: '24px',
          pointerEvents: 'none',
          zIndex: 10,
          padding: '4px',
          background: 'rgba(15, 23, 42, 0.9)',
          borderRadius: '4px',
          border: '1px solid rgba(56, 189, 248, 0.2)',
        }}>
          {[1, 2, 3, 4].map(i => {
            const dist = Math.sqrt(Math.pow(data.nearest_ap.x - data.x, 2) + Math.pow(data.nearest_ap.y - data.y, 2));
            const strength = dist < 400 ? 4 : dist < 800 ? 3 : dist < 1200 ? 2 : 1;
            const isActive = i <= strength;
            
            return (
              <div key={i} className="signal-bar" style={{
                width: '4px',
                height: `${i * 25}%`,
                background: isActive ? '#38bdf8' : 'rgba(255,255,255,0.1)',
                borderRadius: '1px',
                opacity: isActive ? 0.4 + (i * 0.15) : 0.2,
                boxShadow: isActive ? '0 0 8px rgba(56, 189, 248, 0.4)' : 'none',
                animation: 'none'
              }} />
            );
          })}
        </div>
      )}

      {hasAgent && metrics && (
        <div className="node-metrics">
          <div className="metric-item">
            <Cpu size={10} />
            <div className="metric-bar-bg">
              <div className="metric-bar-fill cpu" style={{ width: `${metrics.cpu_percent}%` }} />
            </div>
            <span>{Math.round(metrics.cpu_percent)}%</span>
          </div>
          <div className="metric-item">
            <Activity size={10} />
            <div className="metric-bar-bg">
              <div className="metric-bar-fill ram" style={{ width: `${metrics.ram?.percent || 0}%` }} />
            </div>
            <span>{Math.round(metrics.ram?.percent || 0)}%</span>
          </div>
        </div>
      )}

      {/* Dynamic Handles based on config */}
      {/* Top Handles */}
      {(topHandleType === 'target' || topHandleType === 'both') && (
        <Handle type="target" position={Position.Top} className="node-handle top target" id="top-target" />
      )}
      {(topHandleType === 'source' || topHandleType === 'both') && (
        <Handle type="source" position={Position.Top} className="node-handle top source" id="top-source" />
      )}
      
      {/* Bottom Handles */}
      {(bottomHandleType === 'target' || bottomHandleType === 'both') && (
        <Handle type="target" position={Position.Bottom} className="node-handle bottom target" id="bottom-target" />
      )}
      {(bottomHandleType === 'source' || bottomHandleType === 'both') && (
        <Handle type="source" position={Position.Bottom} className="node-handle bottom source" id="bottom-source" />
      )}
      
      {/* Port status indicator if max_ports is set */}
      {data.max_ports > 0 && (
        <div className="port-count">
          <Layers size={8} /> {data.link_count || 0} / {data.max_ports} Ports
        </div>
      )}
    </div>
  );
});

// --- Custom Edge Component ---
const CustomEdge = React.memo(({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data,
  selected,
}: EdgeProps) => {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetPosition,
    targetX,
    targetY,
  });

  const speed = data?.link_type || '1GbE';
  const isOnline = data?.source_online && data?.target_online;
  const speedColor = !isOnline ? 'rgba(100, 116, 139, 0.4)' : 
    speed.includes('10G') ? '#f59e0b' : 
    (speed.includes('2.5G') || speed.includes('2500')) ? '#d946ef' : 
    speed.includes('1GbE') ? '#38bdf8' : '#94a3b8';

  const { speed: globalSpeed, intensity } = React.useContext(FlowSettingsContext);

  return (
    <>
      <path
        style={{ fill: 'none', stroke: 'transparent', strokeWidth: 20 }}
        className="react-flow__edge-interaction"
        d={edgePath}
      />
      <path
        id={id}
        style={{ 
          ...style, 
          stroke: speedColor, 
          strokeWidth: selected ? 4 : 2,
          strokeOpacity: selected ? 1 : (isOnline ? 0.6 : 0.3),
          strokeDasharray: data.is_wireless || !isOnline ? '5,5' : 'none',
          transition: 'stroke-width 0.2s, stroke-opacity 0.2s',
          shapeRendering: 'optimizeSpeed',
        }}
        className={`react-flow__edge-path ${selected ? 'selected' : ''}`}
        d={edgePath}
        markerEnd={markerEnd}
      />
      
      {/* Particle Animation (only if online and not wireless) */}
      {isOnline && !data.is_wireless && intensity > 0 && (
        <>
          {Array.from({ length: intensity }).map((_, i) => {
            const baseDur = speed.includes('10G') ? 1.4 : speed.includes('2.5G') ? 1.8 : 3;
            const duration = `${baseDur / globalSpeed}s`;
            const startOffset = i * (parseFloat(duration) / intensity);
            
            return (
              <React.Fragment key={i}>
                <circle r="4.5" fill={speedColor} opacity="0.25">
                  <animateMotion
                    dur={duration}
                    repeatCount="indefinite"
                    path={edgePath}
                    begin={`${-startOffset}s`}
                  />
                </circle>
                <circle r="3" fill={speedColor} opacity="0.9">
                  <animateMotion
                    dur={duration}
                    repeatCount="indefinite"
                    path={edgePath}
                    begin={`${-startOffset}s`}
                  />
                </circle>
                <circle r="1.5" fill="#fff" opacity="0.8">
                  <animateMotion
                    dur={duration}
                    repeatCount="indefinite"
                    path={edgePath}
                    begin={`${-startOffset}s`}
                  />
                </circle>
              </React.Fragment>
            );
          })}
        </>
      )}

      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            fontSize: 10,
            pointerEvents: 'all',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            zIndex: 1000,
          }}
          className={`edge-label-container ${selected ? 'selected' : ''}`}
        >
          <div 
            className="edge-speed-badge" 
            style={{ backgroundColor: speedColor, cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              data.onRotateSpeed(id, speed);
            }}
          >
            {speed}
          </div>
          {selected && (
             <button 
                className="edge-delete-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  data.onDeleteLink(id);
                }}
              >
                <Trash2 size={10} />
              </button>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

const nodeTypes = {
  device: DeviceNode,
};

const edgeTypes = {
  custom: CustomEdge,
};

const TopologyMap: React.FC = () => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [selectedEdge, setSelectedEdge] = useState<any>(null);

  // Engine & UI State
  const [flowSpeed, setFlowSpeed] = useState(1.0);
  const [flowIntensity, setFlowIntensity] = useState(2);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isFlowExpanded, setIsFlowExpanded] = useState(window.innerWidth > 768);
  const [stickyDrag, setStickyDrag] = useState(false);
  const [lastPos, setLastPos] = useState<{x: number, y: number} | null>(null);
  
  // Sidebar config state
  const [configMaxPorts, setConfigMaxPorts] = useState<number>(24);
  const [configIsWlan, setConfigIsWlan] = useState<boolean>(false);
  const [configIsAp, setConfigIsAp] = useState<boolean>(false);
  const [configTopHandle, setConfigTopHandle] = useState<string>('target');
  const [configBottomHandle, setConfigBottomHandle] = useState<string>('source');

  // Persistence for Flow Settings
  useEffect(() => {
    const loadFlowSettings = async () => {
      try {
        const settings = await api.getSettings();
        if (settings['topology.flow_speed']) setFlowSpeed(parseFloat(settings['topology.flow_speed']));
        if (settings['topology.flow_intensity']) setFlowIntensity(parseInt(settings['topology.flow_intensity']));
        if (settings['topology.sticky_drag']) setStickyDrag(settings['topology.sticky_drag'] === 'true');
      } catch (err) {
        console.error('Failed to load flow settings:', err);
      }
    };
    loadFlowSettings();
  }, []);

  const saveFlowSetting = useCallback(async (key: string, value: any) => {
    try {
      await api.updateSettings({ [key]: value.toString() });
    } catch (err) {
      console.error(`Failed to save flow setting ${key}:`, err);
    }
  }, []);

  const onRotateSpeed = useCallback(async (edgeId: string, currentSpeed: string, forcedSpeed?: string) => {
    const speeds = ['100Mb', '1GbE', '2.5GbE', '10GbE'];
    const nextSpeed = forcedSpeed || speeds[(speeds.indexOf(currentSpeed) + 1) % speeds.length];
    const linkId = edgeId.replace('e-', '');
    
    try {
      setEdges(eds => eds.map(e => {
        if (e.id === edgeId) {
          const newEdge = { ...e, data: { ...e.data, link_type: nextSpeed } };
          // Update selected edge if it's the one being modified
          if (selectedEdge?.id === edgeId) setSelectedEdge(newEdge);
          return newEdge;
        }
        return e;
      }));
      await api.updateTopologyLink(parseInt(linkId), { link_type: nextSpeed as any });
    } catch (err) { console.error(err); }
  }, [setEdges, selectedEdge]);

  const onDeleteLink = useCallback(async (edgeId: string) => {
    const linkId = edgeId.replace('e-', '');
    try {
      setEdges(eds => eds.filter(e => e.id !== edgeId));
      await api.deleteTopologyLink(parseInt(linkId));
    } catch (err) { console.error(err); }
  }, [setEdges]);

  const fetchData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const { devices, links } = await api.getTopologyMap();
      console.log(`Topology: Loaded ${devices?.length || 0} devices and ${links?.length || 0} links`);

      if (!devices || devices.length === 0) {
        setNodes([]);
        setEdges([]);
        return;
      }

      // Calculate nearest AP for WLAN devices
      const aps = devices.filter((d: any) => d.is_ap);

      const initialNodes = devices.map((dev: any, index: number) => {
        const x = dev.topology_x ?? (index % 5) * 300;
        const y = dev.topology_y ?? Math.floor(index / 5) * 200;
        
        let nearestAp = null;
        if (dev.is_wlan && aps.length > 0) {
          let minDist = Infinity;
          aps.forEach((ap: any) => {
            const apX = ap.topology_x ?? (devices.indexOf(ap) % 5) * 300;
            const apY = ap.topology_y ?? Math.floor(devices.indexOf(ap) / 5) * 200;
            const dist = Math.sqrt(Math.pow(apX - x, 2) + Math.pow(apY - y, 2));
            if (dist < minDist) {
              minDist = dist;
              nearestAp = { x: apX, y: apY, id: ap.id };
            }
          });
        }

        return {
          id: dev.id.toString(),
          type: 'device',
          data: {
            ...dev,
            label: dev.display_name || dev.hostname,
            nearest_ap: nearestAp,
            x: x,
            y: y,
            onDelete: async (id: string) => {
              if (window.confirm('Gerät entfernen?')) {
                await api.deleteDevice(parseInt(id));
                setNodes(nds => nds.filter(n => n.id !== id));
              }
            },
            link_count: links.filter((l: any) => l.source_id === dev.id || l.target_id === dev.id).length
          },
          position: { x, y },
        };
      });

      const initialEdges = links.map((link: any) => {
        const sourceNode = devices.find((d: any) => d.id === link.source_id);
        const targetNode = devices.find((d: any) => d.id === link.target_id);
        const isWireless = sourceNode?.is_wlan || targetNode?.is_wlan;

        return {
          id: `e-${link.id}`,
          source: link.source_id.toString(),
          target: link.target_id.toString(),
          sourceHandle: link.source_handle,
          targetHandle: link.target_handle,
          type: 'custom',
          data: { 
            link_type: link.link_type,
            is_wireless: isWireless,
            source_online: sourceNode?.is_online,
            target_online: targetNode?.is_online,
            onRotateSpeed,
            onDeleteLink
          },
          animated: !isWireless,
          markerEnd: { 
            type: MarkerType.ArrowClosed, 
            color: link.link_type?.includes('10G') ? '#f59e0b' : 
                   (link.link_type?.includes('2.5G') || link.link_type?.includes('2500')) ? '#d946ef' : '#38bdf8' 
          },
        };
      });

      // Optimization: Only update if data actually changed to prevent React Flow re-renders
      setNodes(prevNodes => {
        const simplifiedIncoming = initialNodes.map((n: Node) => ({ id: n.id, data: n.data, position: n.position }));
        const simplifiedCurrent = prevNodes.map((n: Node) => ({ id: n.id, data: n.data, position: n.position }));
        
        if (JSON.stringify(simplifiedIncoming) === JSON.stringify(simplifiedCurrent)) {
          return prevNodes;
        }

        // Preserve selected state and dragging positions
        return initialNodes.map((n: any) => {
          const existing = prevNodes.find(node => node.id === n.id);
          return existing ? { 
            ...n, 
            selected: existing.selected, 
            position: (existing as any).dragging ? existing.position : n.position 
          } : n;
        });
      });

      setEdges(prevEdges => {
        const simplifiedIncoming = initialEdges.map((e: Edge) => ({ id: e.id, data: e.data, source: e.source, target: e.target }));
        const simplifiedCurrent = prevEdges.map((e: Edge) => ({ id: e.id, data: e.data, source: e.source, target: e.target }));
        
        if (JSON.stringify(simplifiedIncoming) === JSON.stringify(simplifiedCurrent)) {
          return prevEdges;
        }

        return initialEdges.map((e: any) => {
          const existing = prevEdges.find(edge => edge.id === e.id);
          return existing ? { ...e, selected: existing.selected } : e;
        });
      });
    } catch (err) { 
      console.error('Topology fetch failed:', err); 
    } finally { 
      setIsRefreshing(false); 
    }
  }, [setNodes, setEdges, onRotateSpeed, onDeleteLink]);

  const onConnect = useCallback((params: Connection) => {
    if (params.source === params.target) return;
    
    // Enforce max ports
    const sourceNode = nodes.find(n => n.id === params.source);
    const targetNode = nodes.find(n => n.id === params.target);
    
    if (sourceNode && sourceNode.data.max_ports > 0) {
      const currentLinks = edges.filter(e => e.source === params.source || e.target === params.source).length;
      if (currentLinks >= sourceNode.data.max_ports) {
        alert(`Port-Limit erreicht! ${sourceNode.data.label} hat bereits ${currentLinks} von ${sourceNode.data.max_ports} Ports belegt.`);
        return;
      }
    }
    
    if (targetNode && targetNode.data.max_ports > 0) {
      const currentLinks = edges.filter(e => e.source === params.target || e.target === params.target).length;
      if (currentLinks >= targetNode.data.max_ports) {
        alert(`Port-Limit erreicht! ${targetNode.data.label} hat bereits ${currentLinks} von ${targetNode.data.max_ports} Ports belegt.`);
        return;
      }
    }

    api.createTopologyLink({
      source_id: parseInt(params.source!),
      target_id: parseInt(params.target!),
      source_handle: params.sourceHandle,
      target_handle: params.targetHandle,
      link_type: '1GbE',
    }).then(res => {
      fetchData();
    }).catch(err => {
      alert("Fehler beim Erstellen der Verbindung. Möglicherweise existiert sie bereits?");
    });
  }, [fetchData, nodes, edges]);


  const saveNodeSettings = async () => {
    if (!selectedNode) return;
    const config = {
      top_handle_type: configTopHandle,
      bottom_handle_type: configBottomHandle,
    };
    
    try {
      await api.updateDevice(selectedNode.id, {
        max_ports: configMaxPorts,
        is_wlan: configIsWlan,
        is_ap: configIsAp,
        topology_config: JSON.stringify(config)
      });
      fetchData();
      setSelectedNode(null);
    } catch (err) { console.error(err); }
  };

  const saveNodePos = async (id: string, pos: { x: number, y: number }) => {
    try {
      await api.updateDevice(parseInt(id), {
        topology_x: Math.round(pos.x),
        topology_y: Math.round(pos.y),
      });
    } catch (err) {
      console.error('Failed to save node position:', err);
    }
  };


  const onNodeDragStart = useCallback((_: any, node: any) => {
    setLastPos({ x: node.position.x, y: node.position.y });
  }, []);

  const onNodeDrag = useCallback((_: any, node: any) => {
    if (!stickyDrag || !lastPos) return;

    const dx = node.position.x - lastPos.x;
    const dy = node.position.y - lastPos.y;
    
    if (dx === 0 && dy === 0) return;

    const neighbors = new Set();
    edges.forEach(e => {
      if (e.source === node.id) neighbors.add(e.target);
      if (e.target === node.id) neighbors.add(e.source);
    });

    setNodes(nds => nds.map(n => {
      if (neighbors.has(n.id)) {
        return {
          ...n,
          position: {
            x: n.position.x + dx,
            y: n.position.y + dy
          }
        };
      }
      return n;
    }));
    
    setLastPos({ x: node.position.x, y: node.position.y });
  }, [stickyDrag, lastPos, edges, setNodes]);

  const onNodeDragStop = useCallback(async (_: any, node: any) => {
    setLastPos(null);
    await saveNodePos(node.id, node.position);
    
    if (stickyDrag) {
      const neighbors = new Set();
      edges.forEach(e => {
        if (e.source === node.id) neighbors.add(e.target);
        if (e.target === node.id) neighbors.add(e.source);
      });

      // Save all moved neighbors
      for (const nid of neighbors) {
        const n = nodes.find(x => x.id === nid);
        if (n) await saveNodePos(n.id.toString(), n.position);
      }
    }
  }, [stickyDrag, edges, nodes]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 60000);
    return () => clearInterval(timer);
  }, [fetchData]);

  const containerRef = React.useRef<HTMLDivElement>(null);

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(err => {
        console.error(`Error attempting to enable full-screen mode: ${err.message}`);
      });
    } else {
      document.exitFullscreen();
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  return (
    <FlowSettingsContext.Provider value={{ speed: flowSpeed, intensity: flowIntensity }}>
      <div 
        ref={containerRef}
        style={{ 
          height: '100%', 
          width: '100%', 
          minHeight: isFullscreen ? '100vh' : '750px', 
          position: 'relative', 
          background: '#0f172a', 
          display: 'flex' 
        }}
      >
      
      {/* Main Flow Area */}
      <div style={{ flex: 1, position: 'relative' }}>
        <div style={{ position: 'absolute', top: '24px', left: '24px', zIndex: 10, display: 'flex', gap: '12px' }}>
          <div className="topology-header">
            <Share2 size={16} className="text-sky-400" />
            Topology Designer
          </div>
          <button className={`refresh-btn ${isRefreshing ? 'spinning' : ''}`} onClick={() => fetchData()} title="Refresh Data">
            <RefreshCw size={16} />
          </button>
          <button className="refresh-btn" onClick={toggleFullscreen} title="Fullscreen Toggle">
            {isFullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
          </button>
        </div>

        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_, node) => {
            setSelectedNode(node);
            setSelectedEdge(null);
            setConfigMaxPorts(node.data.max_ports || 24);
            setConfigIsWlan(!!node.data.is_wlan);
            setConfigIsAp(!!node.data.is_ap);
            try {
              const config = node.data.topology_config ? JSON.parse(node.data.topology_config) : {};
              setConfigTopHandle(config.top_handle_type || 'target');
              setConfigBottomHandle(config.bottom_handle_type || 'source');
            } catch {
              setConfigTopHandle('target');
              setConfigBottomHandle('source');
            }
          }}
          onEdgeClick={(_, edge) => {
            setSelectedEdge(edge);
            setSelectedNode(null);
          }}
          onPaneClick={() => {
            setSelectedNode(null);
            setSelectedEdge(null);
          }}
          onNodeDragStart={onNodeDragStart}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.05}
          maxZoom={4}
        >
          <Background color="#1e293b" gap={32} size={1} />
          <Controls />
        </ReactFlow>

        {/* --- Flow Controls Overlay --- */}
        <div className={`flow-controls ${!isFlowExpanded ? 'collapsed' : ''}`}>
          <div className="flow-controls__header" onClick={() => setIsFlowExpanded(!isFlowExpanded)} style={{ cursor: 'pointer' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
              <Sliders size={14} />
              <span>Flow Engine</span>
            </div>
            {isFlowExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
          
          {isFlowExpanded && (
            <>
              <div className="flow-control-item">
                <div className="flow-control-item__label">
                  <Zap size={12} />
                  <span>Speed: {flowSpeed.toFixed(1)}x</span>
                </div>
                <input 
                  type="range" 
                  min="0.1" 
                  max="3.0" 
                  step="0.1" 
                  value={flowSpeed} 
                  onChange={(e) => {
                    const val = parseFloat(e.target.value);
                    setFlowSpeed(val);
                    saveFlowSetting('topology.flow_speed', val);
                  }}
                />
              </div>

              <div className="flow-control-item">
                <div className="flow-control-item__label">
                  <Wind size={12} />
                  <span>Intensity: {flowIntensity}</span>
                </div>
                <input 
                  type="range" 
                  min="0" 
                  max="5" 
                  step="1" 
                  value={flowIntensity} 
                  onChange={(e) => {
                    const val = parseInt(e.target.value);
                    setFlowIntensity(val);
                    saveFlowSetting('topology.flow_intensity', val);
                  }}
                />
              </div>

              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between',
                padding: '8px 0',
                borderTop: '1px solid rgba(255,255,255,0.05)',
                marginTop: '4px'
              }}>
                <div className="flow-control-item__label">
                  <Layers size={12} />
                  <span>Sticky Drag</span>
                </div>
                <input 
                  type="checkbox" 
                  checked={stickyDrag} 
                  onChange={(e) => {
                    const val = e.target.checked;
                    setStickyDrag(val);
                    saveFlowSetting('topology.sticky_drag', val);
                  }}
                  style={{ cursor: 'pointer' }}
                />
              </div>
              
              {flowIntensity === 0 && (
                <div style={{ fontSize: '9px', color: '#64748b', textAlign: 'center', marginTop: '2px' }}>
                  Animations Disabled
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Settings Sidebar */}
      {(selectedNode || selectedEdge) && (
        <div className="topology-sidebar">
          <div className="sidebar-header">
            <div className="header-title">
              <Settings size={18} />
              {selectedNode ? 'Geräte-Konfiguration' : 'Verbindungs-Info'}
            </div>
            <button className="close-btn" onClick={() => { setSelectedNode(null); setSelectedEdge(null); }}>
              <X size={18} />
            </button>
          </div>

          <div className="sidebar-content">
            {selectedNode && (
              <div className="settings-group">
                <div className="device-preview">
                  {selectedNode.data.is_ap ? (
                    <Radio size={32} className="text-amber-400" />
                  ) : selectedNode.data.virtual_type === 'docker' ? (
                    <Box size={32} className="text-cyan-400" />
                  ) : selectedNode.data.virtual_type === 'vm' ? (
                    <Monitor size={32} className="text-purple-400" />
                  ) : selectedNode.data.is_wlan ? (
                    <Smartphone size={32} className="text-sky-400" />
                  ) : (
                    <Server size={32} className="text-sky-400" />
                  )}
                  <div>
                    <div className="preview-name">{selectedNode.data.label}</div>
                    <div className="preview-ip">{selectedNode.data.ip}</div>
                    {selectedNode.data.virtual_type && (
                      <div className="preview-type">
                        {selectedNode.data.virtual_type.toUpperCase()}
                      </div>
                    )}
                  </div>
                </div>

                <div className="settings-section">
                  <label className="section-label">Geräte-Modus</label>
                  <div className="toggle-group">
                    <label className="toggle-item">
                      <input 
                        type="checkbox" 
                        checked={configIsWlan} 
                        onChange={(e) => setConfigIsWlan(e.target.checked)} 
                      />
                      <div className="toggle-content">
                        <Smartphone size={14} />
                        <span>WLAN Gerät</span>
                      </div>
                    </label>
                    <label className="toggle-item">
                      <input 
                        type="checkbox" 
                        checked={configIsAp} 
                        onChange={(e) => setConfigIsAp(e.target.checked)} 
                      />
                      <div className="toggle-content">
                        <Radio size={14} />
                        <span>Access Point</span>
                      </div>
                    </label>
                  </div>
                </div>

                <div className="input-field">
                  <label>Maximale Ports</label>
                  <input 
                    type="number" 
                    value={configMaxPorts} 
                    onChange={(e) => setConfigMaxPorts(parseInt(e.target.value))} 
                  />
                </div>

                <div className="input-field">
                  <label>Oberer Anschluss (Top)</label>
                  <select value={configTopHandle} onChange={(e) => setConfigTopHandle(e.target.value)}>
                    <option value="target">Input (Target)</option>
                    <option value="source">Output (Source)</option>
                    <option value="both">Beides (Bi-Directional)</option>
                  </select>
                </div>

                <div className="input-field">
                  <label>Unterer Anschluss (Bottom)</label>
                  <select value={configBottomHandle} onChange={(e) => setConfigBottomHandle(e.target.value)}>
                    <option value="source">Output (Source)</option>
                    <option value="target">Input (Target)</option>
                    <option value="both">Beides (Bi-Directional)</option>
                  </select>
                </div>

                <div className="sidebar-actions">
                  <button className="save-btn" onClick={saveNodeSettings}>
                    <Save size={16} /> Speichern
                  </button>
                  <button className="delete-btn" onClick={() => selectedNode.data.onDelete(selectedNode.id)}>
                    <Trash2 size={16} /> Gerät entfernen
                  </button>
                </div>
              </div>
            )}

            {selectedEdge && (
               <div className="settings-group">
                 <div className="edge-info">
                    <Share2 size={32} className="text-amber-400" />
                    <div>
                      <div className="preview-name">Link: {selectedEdge.data.link_type}</div>
                      <div className="preview-ip">ID: {selectedEdge.id}</div>
                    </div>
                 </div>

                 <div className="input-field">
                   <label>Geschwindigkeit</label>
                   <select 
                     value={selectedEdge.data.link_type} 
                     onChange={(e) => onRotateSpeed(selectedEdge.id, selectedEdge.data.link_type, e.target.value)}
                   >
                     <option value="100Mb">100 Mb/s</option>
                     <option value="1GbE">1 Gb/s (1GbE)</option>
                     <option value="2.5GbE">2.5 Gb/s (2.5GbE)</option>
                     <option value="10GbE">10 Gb/s (10GbE)</option>
                   </select>
                 </div>
                 
                 <button className="delete-btn full" onClick={() => onDeleteLink(selectedEdge.id)}>
                    <Trash2 size={16} /> Verbindung trennen
                 </button>
               </div>
            )}
          </div>
        </div>
      )}

      <style>{`
        .topology-header {
          background: rgba(30, 41, 59, 0.8);
          backdrop-filter: blur(20px);
          padding: 10px 20px;
          border-radius: 20px;
          border: 1px solid rgba(255,255,255,0.1);
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 0.875rem;
          font-weight: 800;
          color: #f8fafc;
          box-shadow: 0 20px 40px -10px rgba(0,0,0,0.5);
          text-transform: uppercase;
        }

        .topology-sidebar {
          width: 320px;
          background: #0f172a;
          border-left: 1px solid rgba(255,255,255,0.1);
          display: flex;
          flex-direction: column;
          animation: slideIn 0.3s ease-out;
          z-index: 100;
        }
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }

        .sidebar-header {
          padding: 20px;
          border-bottom: 1px solid rgba(255,255,255,0.05);
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .header-title { display: flex; align-items: center; gap: 10px; font-weight: 800; color: #f1f5f9; }
        .close-btn { background: none; border: none; color: #64748b; cursor: pointer; }

        .sidebar-content { padding: 20px; flex: 1; overflow-y: auto; }
        .device-preview, .edge-info {
          display: flex;
          align-items: center;
          gap: 15px;
          padding: 15px;
          background: rgba(255,255,255,0.03);
          border-radius: 12px;
          margin-bottom: 25px;
        }
        .preview-name { font-weight: 700; color: #f8fafc; }
        .preview-ip { font-size: 0.75rem; color: #94a3b8; }
        .preview-type {
          font-size: 0.65rem;
          color: #64748b;
          background: rgba(255,255,255,0.05);
          padding: 2px 6px;
          border-radius: 4px;
          display: inline-block;
          margin-top: 4px;
          font-weight: 700;
        }

        .input-field { margin-bottom: 20px; }
        .input-field label { display: block; font-size: 0.75rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; margin-bottom: 8px; }
        .input-field input, .input-field select {
          width: 100%;
          background: #0f172a;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 8px;
          padding: 10px;
          color: #f1f5f9;
          font-size: 0.875rem;
        }

        .sidebar-actions { display: flex; flex-direction: column; gap: 10px; margin-top: 30px; }
        .save-btn {
          width: 100%;
          background: #38bdf8;
          color: #0f172a;
          border: none;
          padding: 12px;
          border-radius: 8px;
          font-weight: 800;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          cursor: pointer;
        }
        .delete-btn {
          width: 100%;
          background: rgba(239, 68, 68, 0.1);
          color: #ef4444;
          border: 1px solid rgba(239, 68, 68, 0.2);
          padding: 10px;
          border-radius: 8px;
          font-size: 0.75rem;
          cursor: pointer;
        }
        .delete-btn.full { font-size: 0.875rem; font-weight: 800; padding: 12px; }

        .topology-node {
          background: rgba(15, 23, 42, 0.98);
          color: #f8fafc;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 16px;
          padding: 16px;
          min-width: 240px;
          transition: border-color 0.2s;
          transform: translateZ(0);
        }
        .topology-node.selected {
          border-color: #38bdf8;
          box-shadow: 0 0 20px rgba(56, 189, 248, 0.2);
        }
        .topology-node:hover {
          border-color: rgba(255,255,255,0.2);
        }
        .topology-node.online { border-left: 4px solid #10b981; }
        .topology-node.offline { border-left: 4px solid #ef4444; opacity: 0.8; }
        
        .node-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
        .status-indicator {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          position: absolute;
          bottom: -2px;
          right: -2px;
          border: 2px solid #0f172a;
        }
        .status-indicator.active { background: #10b981; box-shadow: 0 0 8px #10b981; }
        .status-indicator.inactive { background: #ef4444; }

        .node-label { font-weight: 700; font-size: 0.9rem; color: #f8fafc; }
        .node-sublabel { font-size: 0.7rem; color: #94a3b8; font-family: monospace; }
        .node-metrics { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.05); }
        .metric-item { display: flex; align-items: center; gap: 8px; font-size: 0.65rem; color: #94a3b8; }
        .metric-bar-bg { flex: 1; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden; }
        .metric-bar-fill { height: 100%; transition: width 0.3s ease; }
        .metric-bar-fill.cpu { background: #38bdf8; }
        .metric-bar-fill.ram { background: #a855f7; }
        
        .port-count { font-size: 8px; color: #64748b; margin-top: 10px; display: flex; align-items: center; gap: 4px; font-weight: 700; }

        .node-handle { 
          width: 12px !important; 
          height: 12px !important; 
          background: #38bdf8 !important; 
          border: 3px solid #0f172a !important; 
        }
        .node-handle.target { background: #10b981 !important; }
        .node-handle.source { background: #38bdf8 !important; }
        
        .refresh-btn {
          background: rgba(30, 41, 59, 0.8);
          width: 44px;
          height: 44px;
          border-radius: 50%;
          border: 1px solid rgba(255,255,255,0.1);
          display: flex;
          align-items: center;
          justify-content: center;
          color: #38bdf8;
          cursor: pointer;
        }
        .refresh-btn.spinning svg { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse {
          0%, 100% { opacity: 0.4; transform: scaleY(1); }
          50% { opacity: 1; transform: scaleY(1.2); }
        }
        .node-icon-container { position: relative; }
        .wlan-badge {
          position: absolute;
          top: -4px;
          right: -4px;
          background: #38bdf8;
          color: white;
          border-radius: 50%;
          padding: 2px;
          box-shadow: 0 0 10px rgba(56, 189, 248, 0.5);
        }
        
        .host-badge {
          background: rgba(245, 158, 11, 0.2);
          color: #f59e0b;
          border: 1px solid rgba(245, 158, 11, 0.3);
          padding: 1px 4px;
          border-radius: 4px;
          font-size: 8px;
          font-weight: 900;
          display: flex;
          align-items: center;
          gap: 2px;
        }

        .node-parent-info {
          font-size: 8px;
          color: #94a3b8;
          margin-top: 4px;
          display: flex;
          align-items: center;
          gap: 4px;
          font-weight: 600;
          opacity: 0.8;
        }

        .react-flow__edge-path {
          pointer-events: none;
        }
        
        /* Disable heavy effects during interaction */
        .react-flow--dragging .topology-node {
          background: rgba(15, 23, 42, 0.98) !important;
          box-shadow: none !important;
        }
        .react-flow--dragging .react-flow__edge-path.animated {
          animation-play-state: paused;
        }
        .toggle-group {
          display: flex;
          gap: 10px;
          margin-bottom: 15px;
        }
        .toggle-item {
          flex: 1;
          cursor: pointer;
        }
        .toggle-item input { display: none; }
        .toggle-content {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px;
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 8px;
          font-size: 0.75rem;
          color: #94a3b8;
          transition: all 0.2s;
        }
        .toggle-item input:checked + .toggle-content {
          background: rgba(56, 189, 248, 0.1);
          border-color: #38bdf8;
          color: #38bdf8;
        }
        .section-label {
          display: block;
          font-size: 0.7rem;
          text-transform: uppercase;
          color: #64748b;
          margin-bottom: 8px;
          font-weight: 700;
        }
        .flow-controls {
          position: absolute;
          top: 20px;
          right: 20px;
          background: rgba(15, 23, 42, 0.85);
          backdrop-filter: blur(12px);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 12px;
          padding: 12px;
          width: 180px;
          z-index: 1000;
          box-shadow: 0 8px 32px rgba(0,0,0,0.4);
          display: flex;
          flex-direction: column;
          gap: 12px;
          transition: all 0.3s ease;
        }
        .flow-controls.collapsed {
          width: 140px;
          gap: 0;
          padding: 10px;
        }
        .flow-controls__header {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.75rem;
          font-weight: 800;
          color: #38bdf8;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          border-bottom: 1px solid rgba(255, 255, 255, 0.05);
          padding-bottom: 8px;
        }
        .collapsed .flow-controls__header {
          border-bottom: none;
          padding-bottom: 0;
        }
        .flow-control-item {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .flow-control-item__label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.7rem;
          color: #94a3b8;
          font-weight: 600;
        }
        .flow-control-item input[type="range"] {
          -webkit-appearance: none;
          width: 100%;
          height: 4px;
          background: rgba(255,255,255,0.1);
          border-radius: 2px;
          outline: none;
        }
        .flow-control-item input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 12px;
          height: 12px;
          background: #38bdf8;
          border-radius: 50%;
          cursor: pointer;
          box-shadow: 0 0 10px rgba(56, 189, 248, 0.5);
        }
        @media (max-width: 768px) {
          .flow-controls {
            top: auto;
            bottom: 20px;
            right: 10px;
            background: rgba(15, 23, 42, 0.95);
          }
        }
        
        /* --- Styled React Flow Controls --- */
        .react-flow__controls {
          display: flex;
          flex-direction: column;
          gap: 6px;
          background: rgba(15, 23, 42, 0.6) !important;
          backdrop-filter: blur(12px) !important;
          padding: 6px !important;
          border-radius: 12px !important;
          border: 1px solid rgba(255, 255, 255, 0.1) !important;
          box-shadow: 0 8px 32px rgba(0,0,0,0.4) !important;
          left: 20px !important;
          bottom: 20px !important;
        }
        .react-flow__controls-button {
          background: rgba(255, 255, 255, 0.03) !important;
          border-bottom: none !important;
          border: 1px solid rgba(255, 255, 255, 0.05) !important;
          border-radius: 8px !important;
          color: #94a3b8 !important;
          width: 32px !important;
          height: 32px !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
          margin-bottom: 2px !important;
        }
        .react-flow__controls-button:hover {
          background: rgba(56, 189, 248, 0.15) !important;
          color: #38bdf8 !important;
          border-color: rgba(56, 189, 248, 0.4) !important;
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(56, 189, 248, 0.2);
        }
        .react-flow__controls-button svg {
          fill: currentColor !important;
          width: 14px !important;
          height: 14px !important;
        }
        .react-flow__controls-button:active {
          transform: translateY(0) scale(0.95);
        }
      `}</style>
    </div>
    </FlowSettingsContext.Provider>
  );
};

export default TopologyMap;
