import React, { useState, useEffect } from 'react';
import { Loader2, Plus, Server } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type { Device, Rack } from '../../types';

interface RackVisualizerProps {
  devices: Device[];
}

const RackVisualizer: React.FC<RackVisualizerProps> = ({ devices }) => {
  const { t } = useTranslation();
  const [racks, setRacks] = useState<Rack[]>([]);
  const [selectedRack, setSelectedRack] = useState<Rack | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadRacks = async () => {
      try {
        const data = await api.getRacks();
        const list = Array.isArray(data) ? data : [];
        setRacks(list);
        if (list.length > 0) setSelectedRack(list[0]);
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

  if (isLoading) return (
    <div className="rack-state" role="status">
      <Loader2 size={18} className="animate-spin" aria-hidden="true" /> {t('rack.loading')}
    </div>
  );

  if (!selectedRack) return (
    <div className="rack-state rack-state--empty">
      <span className="setup-features__icon" aria-hidden="true"><Server size={18} /></span>
      <h2>{t('rack.empty_title')}</h2>
      <p>{t('rack.empty_desc')}</p>
      <button type="button" className="btn btn-primary" onClick={createDefaultRack}>
        <Plus size={16} aria-hidden="true" /> {t('rack.create_default')}
      </button>
    </div>
  );

  const rackDevices = (Array.isArray(devices) ? devices : []).filter((d) => d.rack_id === selectedRack.id);
  const units = Array.from({ length: selectedRack.units }, (_, i) => selectedRack.units - i);
  const occupied = rackDevices.reduce((acc, d) => acc + (d.rack_height || 1), 0);
  const inventory = [...rackDevices].sort((a, b) => (b.rack_unit || 0) - (a.rack_unit || 0));

  return (
    <div className="rack-view">
      <header className="rack-view__header">
        <div>
          <h2 className="rack-view__title">{selectedRack.name}</h2>
          <p className="rack-view__meta">{t('rack.meta', { width: selectedRack.width, units: selectedRack.units })}</p>
        </div>
        {racks.length > 1 && (
          <div className="segmented" role="group" aria-label={t('rack.select_rack')}>
            {racks.map((r) => (
              <button
                key={r.id}
                type="button"
                className="segmented__option"
                aria-pressed={selectedRack.id === r.id}
                onClick={() => setSelectedRack(r)}
              >
                {r.name}
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="rack-view__body">
        {/* The rack: one row per height unit, top unit first; a device spans rack_height rows */}
        <div className="rack-frame" role="list" aria-label={selectedRack.name}>
          {units.map((u) => {
            const device = rackDevices.find((d) => d.rack_unit === u);
            const isCovered = rackDevices.some((d) =>
              d.rack_unit !== null && d.rack_unit > u && (d.rack_unit - (d.rack_height || 1) < u)
            );
            if (isCovered && !device) return null;

            if (!device) {
              return (
                <div key={u} className="rack-unit" aria-hidden="true">
                  <span className="rack-unit__number">{u}</span>
                </div>
              );
            }

            const height = device.rack_height || 1;
            return (
              <div
                key={u}
                role="listitem"
                className="rack-device"
                style={{ height: `calc(${height} * var(--rack-unit-height))` }}
              >
                <span className="rack-unit__number">{u}</span>
                <span className={`status-dot ${device.is_online ? 'status-dot--online' : 'status-dot--offline'}`} aria-hidden="true" />
                <span className="rack-device__text">
                  <span className="rack-device__name">{device.display_name || device.hostname || device.ip}</span>
                  <span className="rack-device__meta">{device.ip} · {t('rack.units', { count: height })}</span>
                </span>
              </div>
            );
          })}
        </div>

        <aside className="rack-side">
          <dl className="setup-scan__stats">
            <div>
              <dt>{t('rack.occupied')}</dt>
              <dd>{occupied} <span className="rack-side__of">/ {selectedRack.units}</span></dd>
            </div>
            <div>
              <dt>{t('rack.devices')}</dt>
              <dd>{rackDevices.length}</dd>
            </div>
          </dl>

          <h3 className="rack-side__title">{t('rack.inventory')}</h3>
          {inventory.length === 0 ? (
            <p className="settings-empty">{t('rack.inventory_empty')}</p>
          ) : (
            <ul className="settings-list">
              {inventory.map((d) => (
                <li key={d.id} className="settings-list__row">
                  <span className="rack-side__device">
                    <span
                      className={`status-dot ${d.is_online ? 'status-dot--online' : 'status-dot--offline'}`}
                      role="img"
                      aria-label={d.is_online ? t('network.online') : t('network.offline')}
                    />
                    <span className="settings-list__name">{d.display_name || d.hostname || d.ip}</span>
                  </span>
                  <span className="device-tag">{t('rack.position', { unit: d.rack_unit, count: d.rack_height || 1 })}</span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
};

export default RackVisualizer;
