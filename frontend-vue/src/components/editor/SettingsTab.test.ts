import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import type { Device } from '@/types';
import { initialFormData } from '@/lib/deviceForm';
import SettingsTab from './SettingsTab.vue';

vi.mock('@/api/client', () => ({ api: {} }));
vi.mock('@/stores/appearance', () => ({
  useAppearance: () => ({ load: vi.fn(async () => {}), orbitVisibility: {}, setOrbitVisible: vi.fn(async () => {}) }),
}));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('@/components/orbit/orbitModel', () => ({ isOnOrbit: () => true }));

const device = { id: 1, ip: '192.0.2.1', services: [], dns_names: { '1': 'nas.lan' } } as unknown as Device;

function render(extra: Record<string, unknown> = {}) {
  const form = { ...initialFormData(device), rack_unit: 4, rack_height: 2 };
  const wrapper = mount(SettingsTab, { props: { form, device, devices: [], groups: [], racks: [], refreshing: false, ...extra } });
  return { wrapper, form };
}

describe('SettingsTab', () => {
  it('passes a hostname source choice on to the editor', async () => {
    const { wrapper } = render();
    await wrapper.get('[data-test="hostname-source"]').setValue('dns1');
    expect(wrapper.emitted('hostnameSource')).toEqual([['dns1']]);
  });

  it('locks the hostname source while it is being saved', () => {
    expect(render({ savingSource: true }).wrapper.get('[data-test="hostname-source"]').attributes('disabled')).toBeDefined();
  });

  it('clears the rack unit but keeps at least one unit of height', async () => {
    const { wrapper, form } = render();
    const [unit, height] = wrapper.findAll('input[type="number"]');
    await unit.setValue('');
    await height.setValue('');
    expect(form.rack_unit).toBeNull();
    expect(form.rack_height).toBe(1);
  });

  it('submits without reloading the page', async () => {
    const { wrapper } = render();
    await wrapper.get('form').trigger('submit');
    expect(wrapper.emitted('submit')).toHaveLength(1);
  });
});
