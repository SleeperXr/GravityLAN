/**
 * Readable error messages for known backend errors. The API answers in English (`detail` of an HTTPException);
 * the ones the UI can run into are mapped to translated texts here. Anything unknown is shown as it came.
 */
import { t } from '@/i18n';

interface KnownError {
  pattern: RegExp;
  key: string;
  /** Names of the pattern's capture groups, in order, passed to the text */
  params?: string[];
}

const KNOWN_ERRORS: KnownError[] = [
  { pattern: /^Rack not found$/, key: 'rack_not_found' },
  { pattern: /^Rack item not found$/, key: 'rack_item_not_found' },
  { pattern: /^The item does not fit inside the rack$/, key: 'rack_no_fit' },
  { pattern: /^Unit already taken by (.+)$/, key: 'rack_unit_taken', params: ['name'] },
  { pattern: /^(.+) sits on unit (\d+); move it before making the rack smaller$/, key: 'rack_too_small', params: ['name', 'unit'] },
  { pattern: /^This field cannot be cleared$/, key: 'field_required' },
  { pattern: /^A port that would be removed still has a cable$/, key: 'port_removed_cabled' },
  { pattern: /^Owner not found$/, key: 'owner_not_found' },
  { pattern: /^Port not found$/, key: 'port_not_found' },
  { pattern: /^A cable needs two different ports$/, key: 'cable_same_port' },
  { pattern: /^Both ends are on the same device$/, key: 'cable_same_owner' },
  { pattern: /^A port already has a cable$/, key: 'port_busy' },
  { pattern: /^Cable not found$/, key: 'cable_not_found' },
  { pattern: /^A cable needs a type$/, key: 'cable_type_required' },
];

/** The text of a backend error, translated when the API sent a known `detail`. */
export function apiErrorMessage(err: unknown): string {
  const raw = err instanceof Error ? err.message : typeof err === 'string' ? err : '';
  const text = raw.trim();
  for (const known of KNOWN_ERRORS) {
    const match = known.pattern.exec(text);
    if (!match) continue;
    const params = Object.fromEntries((known.params ?? []).map((name, i) => [name, match[i + 1]]));
    return t(`gv.api_error.${known.key}`, params);
  }
  return raw || t('gv.api_error.unknown');
}
