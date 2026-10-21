/**
 * i18n for GravityUI: the same i18next setup and translation files as the React UI, so both
 * show identical texts and share the language choice (localStorage key `i18nextLng`).
 * Keys that only the Vue UI needs live under `gv.*` in src/locales/*.json.
 */
import i18next, { type TOptions } from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { computed, readonly, ref } from 'vue';
import translationDE from '@shared/locales/de/translation.json';
import translationEN from '@shared/locales/en/translation.json';
import gravityDE from '@/locales/de.json';
import gravityEN from '@/locales/en.json';

export type Locale = 'de' | 'en';

void i18next.use(LanguageDetector).init({
  resources: {
    en: { translation: { ...translationEN, ...gravityEN } },
    de: { translation: { ...translationDE, ...gravityDE } },
  },
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  initAsync: false,
});

const current = ref(i18next.resolvedLanguage ?? i18next.language ?? 'en');
i18next.on('languageChanged', (lng) => {
  current.value = lng;
  document.documentElement.lang = normalize(lng);
});
document.documentElement.lang = normalize(current.value);

function normalize(lng: string): Locale {
  return lng.toLowerCase().startsWith('de') ? 'de' : 'en';
}

/** Translate a key. Reads the reactive locale, so templates re-render on a language switch. */
export function t(key: string, options?: TOptions): string {
  void current.value;
  return i18next.t(key, options) as string;
}

export const locale = computed<Locale>(() => normalize(current.value));

export function setLocale(next: Locale) {
  void i18next.changeLanguage(next);
}

/** Locale-aware number/date formatting for the active language. */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(locale.value === 'de' ? 'de-DE' : 'en-US', options).format(value);
}

export function formatDateTime(value: string | number | Date, options?: Intl.DateTimeFormatOptions): string {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat(locale.value === 'de' ? 'de-DE' : 'en-US', options ?? { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function useI18n() {
  return {
    t,
    locale: readonly(locale),
    setLocale,
    toggleLocale: () => setLocale(locale.value === 'de' ? 'en' : 'de'),
    formatNumber,
    formatDateTime,
  };
}

export { i18next };
