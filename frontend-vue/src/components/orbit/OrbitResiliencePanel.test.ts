import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { setLocale } from '@/i18n';
import OrbitResiliencePanel from './OrbitResiliencePanel.vue';

describe('OrbitResiliencePanel: calculated, not measured', () => {
  beforeEach(() => setLocale('de'));

  it('says the picture is calculated and that backups would have to take over, not that they carry traffic', () => {
    const w = mount(OrbitResiliencePanel, {
      props: { points: [], activeBackups: 2, cutOff: [{ id: 7, label: 'NAS', unlinked: false }] },
    });
    expect(w.get('[data-testid="resilience-computed-hint"]').text()).toBe(
      'Berechnet aus den Verbindungen auf der Karte und dem Online-Status. Verkehr wird nicht gemessen.',
    );
    expect(w.text()).toContain('2 Backup-Leitungen müssten jetzt übernehmen');
    expect(w.text()).toContain('1 Gerät online, aber ohne eingetragenen Weg zum Kern');
    expect(w.text()).not.toContain('gerade aktiv');
  });
});
