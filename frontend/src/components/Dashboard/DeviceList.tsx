import { Device } from '../../types';
import { ServiceBadge } from './ServiceBadge';
import { Edit3, Cpu, Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface DeviceListProps {
  devices: Device[];
  onEdit: (device: Device) => void;
}

export function DeviceList({ devices, onEdit }: DeviceListProps) {
  const { t } = useTranslation();

  return (
    <div className="device-list-view">
      <div className="device-list-container">
        {devices.map((device) => (
          <div key={device.id} className="device-list-item" onClick={() => onEdit(device)}>
            <div className="device-list-item__status">
              <span className={`status-dot ${device.is_online ? 'online' : 'offline'}`} />
            </div>
            
            <div className="device-list-item__info">
              <div className="device-list-item__name">{device.display_name || device.ip}</div>
              <div className="device-list-item__ip">{device.ip}</div>
            </div>

            {device.has_agent && device.agent_info?.metrics && (
              <div className="device-list-item__metrics hide-mobile">
                <div className="mini-metric" title="CPU">
                  <Cpu size={12} />
                  <span>{device.agent_info.metrics.cpu_usage}%</span>
                </div>
                <div className="mini-metric" title="RAM">
                  <Database size={12} />
                  <span>{device.agent_info.metrics.memory_usage}%</span>
                </div>
              </div>
            )}

            <div className="device-list-item__services">
              {/* Named chips: icons alone don't tell two web UIs apart on a phone */}
              {device.services?.map((service) => (
                <ServiceBadge
                  key={service.id}
                  service={service}
                  ip={device.ip}
                />
              ))}
            </div>

            <div className="device-list-item__actions">
              <button
                type="button"
                className="device-card__icon-btn"
                aria-label={`${t('dashboard.edit_device')}: ${device.display_name || device.ip}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit(device);
                }}
              >
                <Edit3 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        .device-list-view {
          padding: 0 var(--space-sm);
        }
        .device-list-container {
          background: var(--bg-card);
          border-radius: var(--radius-lg);
          overflow: hidden;
          border: 1px solid var(--border-subtle);
        }
        .device-list-item {
          display: flex;
          align-items: center;
          min-height: 64px;
          padding: var(--space-sm) var(--space-md);
          gap: var(--space-md);
          border-bottom: 1px solid var(--border-subtle);
          cursor: pointer;
          transition: background 0.2s ease;
        }
        .device-list-item:last-child {
          border-bottom: none;
        }
        .device-list-item:hover {
          background: var(--bg-elevated);
        }
        .device-list-item__status {
          flex-shrink: 0;
        }
        .status-dot {
          display: block;
          width: 10px;
          height: 10px;
          border-radius: 50%;
        }
        .status-dot.online {
          background: var(--accent-success);
        }
        .status-dot.offline {
          background: transparent;
          box-shadow: inset 0 0 0 2px var(--accent-danger);
        }
        
        .device-list-item__info {
          flex: 1;
          min-width: 0;
        }
        .device-list-item__name {
          font-weight: 700;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          font-size: 1rem;
          color: var(--text-primary);
        }
        .device-list-item__ip {
          font-size: 0.8rem;
          color: var(--text-secondary);
          font-family: var(--font-mono);
          opacity: 0.8;
        }
        
        .device-list-item__metrics {
          display: flex;
          gap: var(--space-md);
          margin-right: var(--space-md);
        }
        .mini-metric {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.75rem;
          color: var(--text-secondary);
          background: rgba(255,255,255,0.03);
          padding: 2px 8px;
          border-radius: 4px;
        }
        
        .device-list-item__services {
          display: flex;
          gap: 6px;
          flex-shrink: 0;
          align-items: center;
          justify-content: flex-end;
          flex-wrap: wrap;
          max-width: 300px;
        }
        
        .device-list-item__actions {
          flex-shrink: 0;
          margin-left: var(--space-sm);
        }

        @media (max-width: 768px) {
          .hide-mobile {
            display: none;
          }
          .device-list-item {
            flex-wrap: wrap;
            padding: var(--space-md);
            gap: var(--space-sm);
          }
          .device-list-item__status {
            order: 1;
          }
          .device-list-item__info {
            order: 2;
            flex: 1;
          }
          .device-list-item__actions {
            order: 3;
          }
          .device-list-item__services {
            order: 4;
            width: 100%;
            justify-content: flex-start;
            margin-top: 4px;
            padding-left: 26px; /* Align with name after status dot */
          }
        }
      `}} />
    </div>
  );
}
