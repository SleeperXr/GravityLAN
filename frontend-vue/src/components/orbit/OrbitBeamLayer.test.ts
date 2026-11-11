import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { setLocale } from '@/i18n';
import type { LightBeam } from './orbitModel';
import OrbitBeamLayer from './OrbitBeamLayer.vue';

const beam = (extra: Partial<LightBeam> = {}): LightBeam => ({
  id: 1,
  sourceId: 1,
  targetId: 2,
  linkType: '1GbE',
  color: '#00aaff',
  interrupted: false,
  isWireless: false,
  isPrimaryBridge: true,
  isBackup: false,
  failover: false,
  ...extra,
});

const render = (beams: LightBeam[]) =>
  mount(OrbitBeamLayer, {
    props: {
      beams,
      pos: (id: number) => ({ x: id * 100, y: 0 }),
      centreOf: () => null,
      dim: () => 1,
      selectedId: null,
      animated: true,
      connecting: null,
      trace: { segments: [], hops: [] },
    },
    attachTo: document.body,
  });

describe('OrbitBeamLayer: a calculated failover never looks measured', () => {
  beforeEach(() => setLocale('de'));

  it('labels a backup that has to take over as needed, explains it is calculated and draws no photon', () => {
    const w = render([beam({ isBackup: true, isPrimaryBridge: false, failover: true })]);
    expect(w.text()).toContain('Backup nötig · 1GbE');
    expect(w.text()).not.toContain('aktiv');
    expect(w.find('title').text()).toContain('misst GravityLAN nicht');
    expect(w.find('.photon-pulse').exists()).toBe(false);
    // The core line stays dashed
    const dashes = w.findAll('path').map((p) => p.attributes('stroke-dasharray'));
    expect(dashes).toContain('10 5');
    w.unmount();
  });

  it('keeps the photon on an ordinary primary link, without a calculation note', () => {
    const w = render([beam()]);
    expect(w.find('.photon-pulse').exists()).toBe(true);
    expect(w.find('title').exists()).toBe(false);
    w.unmount();
  });

  it('widens the label pill so the longer English label fits', () => {
    setLocale('en');
    const w = render([beam({ isBackup: true, isPrimaryBridge: false, failover: true, linkType: '10GbE' })]);
    const label = 'Backup needed · 10GbE';
    expect(w.text()).toContain(label);
    expect(Number(w.find('rect').attributes('width'))).toBeGreaterThanOrEqual(label.length * 6.5);
    w.unmount();
  });
});
