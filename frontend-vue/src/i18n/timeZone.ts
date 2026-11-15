/**
 * The time zone every time in GravityUI is shown in. The backend sends times in UTC with their zone;
 * the browser turns them into this zone, so logs, charts, audit and agents all show the same clock,
 * wherever the server runs and whatever TZ its container has. Empty means "the browser's own zone".
 * Kept per browser, like the language.
 */
import { ref } from 'vue';

const STORAGE_KEY = 'gravitylan_timezone';

export function isValidTimeZone(zone: string): boolean {
  if (!zone) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** The zone the operating system / browser reports, UTC when it reports none. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function stored(): string {
  try {
    const zone = localStorage.getItem(STORAGE_KEY) ?? '';
    return isValidTimeZone(zone) ? zone : '';
  } catch {
    return '';
  }
}

/** The chosen zone, '' to follow the browser. Reactive: templates re-render on a change. */
export const timeZonePreference = ref(stored());

export function setTimeZone(zone: string) {
  const next = isValidTimeZone(zone) ? zone : '';
  timeZonePreference.value = next;
  try {
    if (next) localStorage.setItem(STORAGE_KEY, next);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // private mode or blocked storage: the choice holds until the page reloads
  }
}

/** The zone times are shown in right now. */
export function activeTimeZone(): string {
  return timeZonePreference.value || browserTimeZone();
}

// A change in another tab applies here too
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY) timeZonePreference.value = stored();
  });
}

/** Every IANA zone the browser knows, UTC first. */
export function timeZoneNames(): string[] {
  const all = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
  return ['UTC', ...all.filter((zone) => zone !== 'UTC')];
}

/** "UTC+01:00" for a zone at a given moment (summer time counts). */
export function utcOffsetLabel(zone: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'longOffset' })
      .formatToParts(at)
      .find((p) => p.type === 'timeZoneName')?.value;
    // "GMT+01:00"; some engines write plain "GMT" for a zero offset
    if (!part) return '';
    return part === 'GMT' ? 'UTC+00:00' : part.replace('GMT', 'UTC');
  } catch {
    return '';
  }
}
