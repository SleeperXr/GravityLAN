import { describe, expect, it } from 'vitest';
import type { Service } from '@/types';
import { isClientStandby } from './standby';

const svc = (is_up: boolean) => ({ is_up }) as Service;

describe('isClientStandby', () => {
  it('treats a client with every port closed as asleep', () => {
    expect(isClientStandby({ alert_offline: false, services: [svc(false), svc(false)] })).toBe(true);
  });

  it('keeps reporting devices watched 24/7, clients with one open port and clients without services', () => {
    expect(isClientStandby({ alert_offline: true, services: [svc(false)] })).toBe(false);
    expect(isClientStandby({ alert_offline: undefined, services: [svc(false)] })).toBe(false);
    expect(isClientStandby({ alert_offline: false, services: [svc(false), svc(true)] })).toBe(false);
    expect(isClientStandby({ alert_offline: false, services: [] })).toBe(false);
  });
});
