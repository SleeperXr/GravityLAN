import React, { useCallback, useEffect, useState } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Connection,
  NodeDragHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Share2 } from 'lucide-react';

const TopologyMap: React.FC = () => {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const onConnect = useCallback(
    (params: Connection) => {
      // Persist link to backend
      fetch('/api/topology/links', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_id: parseInt(params.source!),
          target_id: parseInt(params.target!),
          link_type: '1GbE',
        }),
      }).catch(err => console.error('Failed to save link:', err));

      setEdges(eds =>
        addEdge(
          {
            ...params,
            animated: true,
            style: { stroke: '#38bdf8', strokeWidth: 2 },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#38bdf8' },
          },
          eds
        )
      );
    },
    [setEdges]
  );

  // Save node position to backend when drag ends
  const onNodeDragStop: NodeDragHandler = useCallback((_event, node) => {
    fetch(`/api/devices/${node.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topology_x: Math.round(node.position.x),
        topology_y: Math.round(node.position.y),
      }),
    }).catch(err => console.error('Failed to save position:', err));
  }, []);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [devRes, linkRes] = await Promise.all([
        fetch('/api/devices'),
        fetch('/api/topology/links'),
      ]);
      const devices = await devRes.json();
      const links = await linkRes.json();

      const initialNodes = devices.map((dev: any, index: number) => ({
        id: dev.id.toString(),
        data: {
          label: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: dev.status === 'online' ? '#10b981' : '#ef4444',
                  flexShrink: 0,
                }} />
                <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>
                  {dev.display_name || dev.hostname}
                </span>
              </div>
              <div style={{ fontSize: '0.7rem', color: '#94a3b8', paddingLeft: '16px', fontFamily: 'monospace' }}>
                {dev.ip}
              </div>
            </div>
          ),
        },
        // Use persisted topology position if available, otherwise auto-layout
        position: {
          x: dev.topology_x ?? (index % 5) * 260,
          y: dev.topology_y ?? Math.floor(index / 5) * 160,
        },
      }));

      const initialEdges = links.map((link: any) => ({
        id: `e-${link.id}`,
        source: link.source_id.toString(),
        target: link.target_id.toString(),
        animated: true,
        style: { stroke: '#38bdf8', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#38bdf8' },
        label: link.link_type,
        labelStyle: { fill: '#94a3b8', fontSize: 10 },
      }));

      setNodes(initialNodes);
      setEdges(initialEdges);
    } catch (err) {
      console.error('Failed to fetch topology data', err);
    }
  };

  return (
    <div style={{ height: '100%', width: '100%', minHeight: '400px', position: 'relative', background: '#0f172a' }}>
      <div style={{ position: 'absolute', top: '24px', left: '24px', zIndex: 10 }}>
        <div style={{
          background: 'rgba(30, 41, 59, 0.9)',
          backdropFilter: 'blur(12px)',
          padding: '8px 16px',
          borderRadius: '16px',
          border: '1px solid rgba(255,255,255,0.1)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '0.875rem',
          fontWeight: 700,
          color: '#f8fafc',
          boxShadow: '0 10px 25px -5px rgba(0,0,0,0.3)',
        }}>
          <Share2 size={16} color="#38bdf8" />
          Topology Designer — drag to connect devices
        </div>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDragStop={onNodeDragStop}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background color="#1e293b" gap={24} size={1} />
        <Controls />
        <MiniMap
          style={{ background: '#1e293b', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }}
          maskColor="rgba(15, 23, 42, 0.7)"
          nodeColor="#38bdf8"
        />
      </ReactFlow>

      <style>{`
        .react-flow__node {
          background: #1e293b !important;
          color: #f8fafc !important;
          border: 1px solid rgba(255,255,255,0.12) !important;
          border-radius: 12px !important;
          padding: 12px 14px !important;
          font-family: inherit !important;
          min-width: 180px;
          box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
        }
        .react-flow__node:hover {
          border-color: #38bdf8 !important;
        }
        .react-flow__node.selected {
          border-color: #38bdf8 !important;
          box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.35) !important;
        }
        .react-flow__handle {
          background: #38bdf8 !important;
          width: 10px !important;
          height: 10px !important;
          border: 2px solid #0f172a !important;
        }
        .react-flow__edge-path {
          stroke: #38bdf8 !important;
          stroke-width: 2 !important;
        }
        .react-flow__controls {
          background: #1e293b !important;
          border: 1px solid rgba(255,255,255,0.1) !important;
          border-radius: 8px !important;
          overflow: hidden;
          box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
        }
        .react-flow__controls-button {
          background: transparent !important;
          border: none !important;
          border-bottom: 1px solid rgba(255,255,255,0.08) !important;
          color: #94a3b8 !important;
          fill: currentColor !important;
        }
        .react-flow__controls-button:hover {
          background: rgba(255,255,255,0.05) !important;
          color: #f8fafc !important;
        }
        .react-flow__attribution { display: none; }
        .react-flow__background { background: #0f172a !important; }
      `}</style>
    </div>
  );
};

export default TopologyMap;
