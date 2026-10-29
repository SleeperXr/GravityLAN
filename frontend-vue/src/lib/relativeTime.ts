import { formatDateTime, locale } from '@/i18n';

/** Parse an API timestamp; null when missing or not a date. */
export function parseDate(date: string | number | Date | null | undefined): Date | null {
  if (!date) return null;
  const d = date instanceof Date ? date : new Date(date);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "vor 5 Minuten" / "5 minutes ago" relative to `now`; past 30 days the plain date. */
export function relativeTimeText(date: Date, now: number = Date.now()): string {
  const diff = (date.getTime() - now) / 1000;
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat(locale.value === 'de' ? 'de-DE' : 'en-US', { numeric: 'auto' });
  if (abs < 45) return rtf.format(0, 'second');
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day');
  return formatDateTime(date, { dateStyle: 'medium' });
}
