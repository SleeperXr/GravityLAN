import { describe, expect, it } from 'vitest';
import { setLocale } from '@/i18n';
import { apiErrorMessage } from './apiErrors';

describe('apiErrorMessage', () => {
  it('translates a known backend error', () => {
    setLocale('de');
    expect(apiErrorMessage(new Error('A port that would be removed still has a cable'))).toBe(
      'Ein Anschluss, der wegfallen würde, hat noch ein Kabel. Erst das Kabel lösen.',
    );
  });

  it('carries the names and units out of the error into the text', () => {
    setLocale('de');
    expect(apiErrorMessage(new Error('Unit already taken by Core Switch'))).toBe('Der Platz ist schon belegt von „Core Switch“.');
    setLocale('en');
    expect(apiErrorMessage(new Error('Proxmox sits on unit 18; move it before making the rack smaller'))).toBe(
      '“Proxmox” sits on unit 18. Move it before making the rack smaller.',
    );
  });

  it('shows an unknown error as it came, and something readable when there is no text', () => {
    setLocale('de');
    expect(apiErrorMessage(new Error('API Error: 502'))).toBe('API Error: 502');
    expect(apiErrorMessage(null)).toBe('Unbekannter Fehler');
  });
});
