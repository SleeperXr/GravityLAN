import type { Device, DeviceGroup } from '../../types';
import { DeviceCard } from './DeviceCard';

interface GroupSectionProps {
  group: DeviceGroup;
  devices: Device[];
  icon: React.ReactNode;
}

export function GroupSection({ group, devices, icon }: GroupSectionProps) {
  return (
    <section className="group-section">
      <div className="group-section__header">
        <span style={{ color: group.color || 'var(--accent-primary)' }}>{icon}</span>
        <h3 className="group-section__title">{group.name}</h3>
        <span className="group-section__count">{devices.length}</span>
      </div>
      <div className="group-section__devices">
        {devices
          .sort((a, b) => {
            if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
            return a.sort_order - b.sort_order;
          })
          .map((device) => (
            <DeviceCard key={device.id} device={device} />
          ))}
      </div>
    </section>
  );
}
