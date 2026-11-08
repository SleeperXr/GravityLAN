import { describe, expect, it, vi } from 'vitest';
import type { Device } from '@/types';
import { deviceRoleOf, networkPathOf } from './deviceForm';

vi.mock('@/api/client', () => ({ api: {} }));

const dev = (id: number, parent_id: number | null = null) => ({ id, parent_id }) as Device;
const ids = (list: Device[]) => list.map((d) => d.id);

describe('networkPathOf', () => {
  it('lists the parents from the outermost host down', () => {
    expect(ids(networkPathOf(2, [dev(1), dev(2, 1), dev(3, 2)]))).toEqual([1, 2]);
  });

  it('is empty without a parent', () => {
    expect(networkPathOf(null, [dev(1)])).toEqual([]);
  });

  it('stops at a parent that is not known', () => {
    expect(ids(networkPathOf(2, [dev(2, 99)]))).toEqual([2]);
  });

  it('survives parents that point at each other', () => {
    expect(ids(networkPathOf(1, [dev(1, 2), dev(2, 1)]))).toEqual([2, 1]);
  });
});

describe('deviceRoleOf', () => {
  it.each([
    [{ virtual_type: 'docker' }, 'Docker'],
    [{ virtual_type: 'vm' }, 'VM'],
    [{ virtual_type: 'lxc' }, 'lxc'],
    [{ virtual_type: null, is_host: true }, 'Host'],
    [{ virtual_type: null, is_host: false }, null],
  ])('%o is %s', (fields, role) => {
    expect(deviceRoleOf(fields as unknown as Device)).toBe(role);
  });

  it('prefers the virtual type over being a host', () => {
    expect(deviceRoleOf({ virtual_type: 'vm', is_host: true } as unknown as Device)).toBe('VM');
  });
});
