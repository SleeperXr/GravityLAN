import { describe, expect, it } from 'vitest';
import { formatNumber, i18next, locale, setLocale, t } from './index';
import de from '@shared/locales/de/translation.json';
import gvDe from '@/locales/de.json';
import gvEn from '@/locales/en.json';

function keys(obj: object, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) =>
    value && typeof value === 'object' ? keys(value, `${prefix}${key}.`) : [`${prefix}${key}`],
  );
}

describe('i18n', () => {
  it('reads the React translation files', () => {
    setLocale('de');
    expect(t('sidebar.dashboard')).toBe(de.sidebar.dashboard);
  });

  it('interpolates and pluralizes like i18next in React', () => {
    setLocale('en');
    expect(t('gv.racks.free', { count: 3 })).toBe('3 U free');
    expect(i18next.exists('gv.scan.progress')).toBe(true);
  });

  it('switches locale reactively', () => {
    setLocale('de');
    expect(locale.value).toBe('de');
    expect(formatNumber(1234.5)).toBe('1.234,5');
    setLocale('en');
    expect(locale.value).toBe('en');
    expect(formatNumber(1234.5)).toBe('1,234.5');
  });

  it('has the same Vue-only keys in German and English', () => {
    expect(keys(gvDe).sort()).toEqual(keys(gvEn).sort());
  });
});
