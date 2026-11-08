import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import type { Device } from '@/types';
import DeviceDnsNames from './DeviceDnsNames.vue';

const dev = (extra: Partial<Device> = {}) => ({ id: 1, ip: '192.0.2.1', dns_names: { '1': 'nas.lan' }, ...extra }) as Device;
const render = (device: Device, saving = false) => mount(DeviceDnsNames, { props: { device, saving } });
const option = (w: ReturnType<typeof render>, value: string) => w.get(`option[value="${value}"]`).element as HTMLOptionElement;

describe('DeviceDnsNames', () => {
  it('shows nothing for a device without the two-server lookup', () => {
    expect(render(dev({ dns_names: null })).find('[data-test="dns-names"]').exists()).toBe(false);
  });

  it('shows the name a server gave', () => {
    const w = render(dev());
    expect(w.get('[data-test="dns-names"]').text()).toContain('nas.lan');
    expect(w.find('[data-test="dns-reason-1"]').exists()).toBe(false);
  });

  it('says why a server gave no name, with a hint', () => {
    const reason = render(dev({ dns_errors: { '2': 'timeout' } })).get('[data-test="dns-reason-2"]');
    expect(reason.text()).toBe('no answer (timeout)');
    expect(reason.attributes('title')).toContain('2 seconds');
  });

  it.each([[undefined], ['something_new']])('falls back to "no answer" without a hint for reason %s', (known) => {
    const reason = render(dev({ dns_errors: known ? { '2': known } : null })).get('[data-test="dns-reason-2"]');
    expect(reason.text()).toBe('no answer');
    expect(reason.attributes('title')).toBeUndefined();
  });

  it('only offers servers that answered', () => {
    const w = render(dev());
    expect(option(w, 'auto').disabled).toBe(false);
    expect(option(w, 'dns1').disabled).toBe(false);
    expect(option(w, 'dns2').disabled).toBe(true);
  });

  it('keeps the current choice selectable after its server went silent', () => {
    const w = render(dev({ hostname_source: 'dns2' }));
    expect(option(w, 'dns2').disabled).toBe(false);
    expect((w.get('select').element as HTMLSelectElement).value).toBe('dns2');
  });

  it('starts on automatic when nothing was chosen', () => {
    expect((render(dev()).get('select').element as HTMLSelectElement).value).toBe('auto');
  });

  it('reports the chosen source', async () => {
    const w = render(dev());
    await w.get('select').setValue('dns1');
    expect(w.emitted('hostnameSource')).toEqual([['dns1']]);
  });

  it('locks the picker while saving', () => {
    expect(render(dev(), true).get('select').attributes('disabled')).toBeDefined();
  });
});
