import { afterEach, describe, expect, it } from 'vitest';
import { formatDateTime, setLocale } from './index';
import { activeTimeZone, browserTimeZone, setTimeZone, timeZoneNames, timeZonePreference, utcOffsetLabel } from './timeZone';

const moment = new Date('2026-11-15T08:45:36Z');
const clock = () => formatDateTime(moment, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

describe('time zone', () => {
  afterEach(() => setTimeZone(''));

  it('shows every time in the chosen zone, whatever zone the server or browser has', () => {
    setLocale('de');
    setTimeZone('Europe/Berlin');
    expect(clock()).toBe('09:45');
    setTimeZone('America/New_York');
    expect(clock()).toBe('03:45');
    setTimeZone('Asia/Kolkata');
    expect(clock()).toBe('14:15');
    setTimeZone('UTC');
    expect(clock()).toBe('08:45');
  });

  it('follows the browser until a zone is chosen, and remembers the choice', () => {
    expect(activeTimeZone()).toBe(browserTimeZone());
    setTimeZone('Australia/Sydney');
    expect(localStorage.getItem('gravitylan_timezone')).toBe('Australia/Sydney');
    setTimeZone('');
    expect(localStorage.getItem('gravitylan_timezone')).toBeNull();
    expect(activeTimeZone()).toBe(browserTimeZone());
  });

  it('ignores a zone the browser does not know instead of breaking every date', () => {
    setTimeZone('Mars/Olympus_Mons');
    expect(timeZonePreference.value).toBe('');
    expect(() => clock()).not.toThrow();
  });

  it('lists UTC first and labels offsets with summer time', () => {
    expect(timeZoneNames()[0]).toBe('UTC');
    expect(utcOffsetLabel('Europe/Berlin', new Date('2026-01-15T12:00:00Z'))).toBe('UTC+01:00');
    expect(utcOffsetLabel('Europe/Berlin', new Date('2026-07-15T12:00:00Z'))).toBe('UTC+02:00');
    expect(utcOffsetLabel('UTC')).toBe('UTC+00:00');
  });
});
