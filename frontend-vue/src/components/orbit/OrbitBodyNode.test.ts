import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { t } from '@/i18n';
import OrbitBodyNode from './OrbitBodyNode.vue';
import type { LabelPlacement } from './orbitLayout';
import type { OrbitBody } from './orbitModel';

const STRIKE = 'line[stroke="var(--gl-danger)"]';
const HALO = 'circle[fill-opacity="0.14"]';
const label: LabelPlacement = { x: 0, y: 20, anchor: 'middle', side: 'below' };

const body = (extra: Partial<OrbitBody> = {}) =>
  ({
    id: 1,
    kind: 'planet',
    state: 'online',
    color: '#123456',
    rings: ['#123456'],
    device: { ip: '192.0.2.1', display_name: 'nas', is_ap: false, is_wlan: false },
    ...extra,
  }) as unknown as OrbitBody;

function render(b: OrbitBody = body(), props: Record<string, unknown> = {}) {
  return mount(OrbitBodyNode, {
    props: { body: b, pos: { x: 10, y: 20 }, label, labelScale: 1, editing: false, selected: false, dim: 1, badge: null, ...props },
  });
}

describe('OrbitBodyNode', () => {
  describe('state never rides on colour alone', () => {
    it('shows nothing extra for an online body', () => {
      const w = render();
      expect(w.attributes('aria-label')).toBe('nas (192.0.2.1)');
      expect(w.find(HALO).exists()).toBe(false);
      expect(w.find(STRIKE).exists()).toBe(false);
      expect(w.findAll('text').map((x) => x.text())).toEqual(['nas', '192.0.2.1']);
    });

    it('strikes an offline body through, says so and names the state', () => {
      const w = render(body({ state: 'offline' }));
      expect(w.attributes('aria-label')).toBe(`nas (192.0.2.1), ${t('gv.orbit.state_offline')}`);
      expect(w.find(STRIKE).exists()).toBe(true);
      expect(w.findAll('text').map((x) => x.text())).toContain(t('gv.plan.dropped'));
    });

    it('marks a degraded body with a "!" and names the state', () => {
      const w = render(body({ state: 'degraded' }));
      expect(w.attributes('aria-label')).toBe(`nas (192.0.2.1), ${t('gv.orbit.state_degraded')}`);
      expect(w.find(STRIKE).exists()).toBe(false);
      const texts = w.findAll('text').map((x) => x.text());
      expect(texts).toContain('!');
      expect(texts).toContain(t('gv.plan.degraded'));
    });

    it('keeps the halo findable at overview zoom, dashed only when offline', () => {
      expect(render(body({ state: 'offline' }), { labelScale: 2 }).get(HALO).attributes('stroke-dasharray')).toBe('6 6');
      expect(render(body({ state: 'degraded' })).get(HALO).attributes('stroke-dasharray')).toBeUndefined();
    });

    it('still names the state when the label is hidden', () => {
      const w = render(body({ state: 'offline' }), { label: null });
      expect(w.findAll('text')).toHaveLength(0);
      expect(w.attributes('aria-label')).toContain(t('gv.orbit.state_offline'));
    });
  });

  it('fades by the given dim, an offline body a little more', () => {
    expect(render(body(), { dim: 0.5 }).attributes('style')).toContain('opacity: 0.5');
    expect(render(body({ state: 'offline' }), { dim: 0.5 }).attributes('style')).toContain('opacity: 0.35');
  });

  it('sits at its position', () => {
    expect(render().attributes('transform')).toBe('translate(10, 20)');
  });

  it('shows the role pill on planets only', () => {
    expect(render(body(), { badge: 'SW' }).findAll('text').map((x) => x.text())).toContain('SW');
    expect(render(body({ kind: 'moon' }), { badge: 'SW' }).findAll('text').map((x) => x.text())).not.toContain('SW');
  });

  it('draws the second network of a multi-homed body, but not on a star', () => {
    const rings = ['#123456', '#abcdef'];
    expect(render(body({ rings })).find('circle[stroke="#abcdef"]').exists()).toBe(true);
    expect(render(body({ rings, kind: 'star' })).find('circle[stroke="#abcdef"]').exists()).toBe(false);
  });

  it('rings a selected body', () => {
    expect(render(body(), { selected: true }).find('circle[stroke="var(--gl-fg)"]').exists()).toBe(true);
    expect(render().find('circle[stroke="var(--gl-fg)"]').exists()).toBe(false);
  });

  it.each(['enter', 'space'])('activates with the %s key', async (key) => {
    const w = render();
    await w.trigger(`keydown.${key}`);
    expect(w.emitted('click')).toHaveLength(1);
  });

  it('offers the beam handle only while editing', async () => {
    expect(render().find('.opacity-80').exists()).toBe(false);
    const w = render(body(), { editing: true });
    await w.get('.opacity-80').trigger('pointerdown');
    expect(w.emitted('beamStart')).toHaveLength(1);
  });
});
