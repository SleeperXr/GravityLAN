import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import type { Device, DeviceGroup } from '@/types';
import { setLocale } from '@/i18n';
import GroupSection from './GroupSection.vue';
import { GridStack } from 'gridstack';

const mockGridInstance = {
  destroy: vi.fn(),
  on: vi.fn(),
  removeWidget: vi.fn(),
  float: vi.fn(),
  compact: vi.fn(),
};

vi.mock('gridstack', () => ({
  GridStack: {
    init: vi.fn(() => mockGridInstance),
  },
}));

vi.mock('./DeviceCard.vue', () => ({
  default: {
    name: 'DeviceCard',
    props: ['device', 'editMode', 'selected'],
    template: '<div class="device-card-mock" :data-id="device.id">{{ device.display_name }}</div>',
  },
}));

vi.mock('./DeviceList.vue', () => ({
  default: {
    name: 'DeviceList',
    props: ['devices'],
    template: '<div class="device-list-mock">{{ devices.length }}</div>',
  },
}));

const makeDevice = (extra: Partial<Device> = {}): Device =>
  ({
    id: 1,
    ip: '192.168.1.10',
    mac: '00:11:22:33:44:55',
    hostname: 'test-device',
    display_name: 'Test Device',
    device_type: 'generic',
    device_subtype: 'generic',
    group_id: 1,
    sort_order: 0,
    is_pinned: false,
    is_hidden: false,
    x: 0,
    y: 0,
    w: 4,
    h: 3,
    notes: null,
    first_seen: '2026-01-01',
    last_seen: '2026-01-02',
    is_online: true,
    status_changed_at: '2026-01-01',
    is_reserved: false,
    virtual_type: null,
    has_agent: false,
    services: [],
    ...extra,
  }) as Device;

const makeGroup = (extra: Partial<DeviceGroup> = {}): DeviceGroup =>
  ({
    id: 1,
    name: 'Lab Devices',
    sort_order: 0,
    color: '#ff0000',
    icon: 'server',
    ...extra,
  }) as DeviceGroup;

beforeEach(() => {
  setLocale('en');
  vi.clearAllMocks();
});

describe('GroupSection', () => {
  it('renders group name when group is provided', () => {
    const wrapper = mount(GroupSection, {
      props: {
        group: makeGroup({ name: 'Home Network' }),
        devices: [makeDevice()],
        isFirst: true,
        isLast: false,
        collapsed: false,
        editMode: false,
        viewMode: 'grid',
        selectedIds: new Set<number>(),
      },
    });

    expect(wrapper.text()).toContain('Home Network');
  });

  it('renders unassigned label when group is null', () => {
    const wrapper = mount(GroupSection, {
      props: {
        group: null,
        devices: [makeDevice()],
        isFirst: true,
        isLast: true,
        collapsed: false,
        editMode: false,
        viewMode: 'grid',
        selectedIds: new Set<number>(),
      },
    });

    expect(wrapper.find('h2').text()).toBe('Unassigned Devices');
  });

  it('emits toggle event when clicking group header button', async () => {
    const wrapper = mount(GroupSection, {
      props: {
        group: makeGroup(),
        devices: [makeDevice()],
        isFirst: true,
        isLast: false,
        collapsed: false,
        editMode: false,
        viewMode: 'grid',
        selectedIds: new Set<number>(),
      },
    });

    const toggleBtn = wrapper.find('button[type="button"]');
    await toggleBtn.trigger('click');
    expect(wrapper.emitted('toggle')).toHaveLength(1);
  });

  it('renders move buttons in edit mode and respects isFirst / isLast disabled states', async () => {
    const wrapper = mount(GroupSection, {
      props: {
        group: makeGroup(),
        devices: [makeDevice()],
        isFirst: true,
        isLast: false,
        collapsed: false,
        editMode: true,
        viewMode: 'grid',
        selectedIds: new Set<number>(),
      },
    });

    const moveBtns = wrapper.findAll('.flex.gap-1 button');
    expect(moveBtns).toHaveLength(2);
    expect(moveBtns[0].attributes('disabled')).toBeDefined(); // isFirst = true
    expect(moveBtns[1].attributes('disabled')).toBeUndefined(); // isLast = false

    await moveBtns[1].trigger('click');
    expect(wrapper.emitted('move')).toEqual([['down']]);
  });

  it('renders DeviceList in list viewMode', () => {
    const wrapper = mount(GroupSection, {
      props: {
        group: makeGroup(),
        devices: [makeDevice({ id: 10 }), makeDevice({ id: 20 })],
        isFirst: false,
        isLast: false,
        collapsed: false,
        editMode: false,
        viewMode: 'list',
        selectedIds: new Set<number>(),
      },
    });

    expect(wrapper.find('.device-list-mock').exists()).toBe(true);
    expect(wrapper.find('.grid-stack').exists()).toBe(false);
  });

  it('initializes GridStack and synchronizes tile attributes in grid mode', async () => {
    const dev1 = makeDevice({ id: 101, x: 2, y: 1, w: 4, h: 3 });
    const dev2 = makeDevice({ id: 102, x: null, y: null, w: null, h: null });

    const wrapper = mount(GroupSection, {
      props: {
        group: makeGroup(),
        devices: [dev1, dev2],
        isFirst: true,
        isLast: false,
        collapsed: false,
        editMode: false,
        filtering: false,
        viewMode: 'grid',
        selectedIds: new Set<number>(),
      },
    });

    await wrapper.vm.$nextTick();

    const items = wrapper.findAll('.grid-stack-item');
    expect(items).toHaveLength(2);

    // dev1 has saved coordinates
    expect(items[0].attributes('gs-x')).toBe('2');
    expect(items[0].attributes('gs-y')).toBe('1');
    expect(items[0].attributes('gs-w')).toBe('4');
    expect(items[0].attributes('gs-h')).toBe('3');

    // dev2 has no saved coordinates -> autoPosition
    expect(items[1].attributes('gs-auto-position')).toBe('true');
    expect(items[1].attributes('gs-w')).toBe('4');
    expect(items[1].attributes('gs-h')).toBe('3');

    expect(GridStack.init).toHaveBeenCalled();
  });

  it('exposes compact() method which calls GridStack compact', async () => {
    const wrapper = mount(GroupSection, {
      props: {
        group: makeGroup(),
        devices: [makeDevice()],
        isFirst: true,
        isLast: false,
        collapsed: false,
        editMode: false,
        viewMode: 'grid',
        selectedIds: new Set<number>(),
      },
    });

    await wrapper.vm.$nextTick();
    (wrapper.vm as unknown as { compact: () => void }).compact();

    expect(mockGridInstance.compact).toHaveBeenCalled();
  });
});
