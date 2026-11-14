import { beforeEach, describe, expect, it } from 'vitest';
import { DESIGN_TOKENS, applyCustomColors, cssVar, designTemplate, parseDesign } from './customThemes';

const design = (patch: Record<string, unknown> = {}) => JSON.stringify({ format: 'gravityui-design', name: 'Ocean', base: 'dark', colors: { surface: '#102030', 'line-1': '#ABCDEF' }, ...patch });

describe('parseDesign', () => {
  it('accepts a valid design and lower-cases its colours', () => {
    const result = parseDesign(design());
    expect(result).toEqual({ ok: true, theme: { name: 'Ocean', base: 'dark', colors: { surface: '#102030', 'line-1': '#abcdef' } } });
  });

  it.each([
    ['not json', '{name:', 'not_json'],
    ['an array', '[]', 'not_object'],
    ['no name', design({ name: '  ' }), 'name'],
    ['a long name', design({ name: 'x'.repeat(41) }), 'name'],
    ['an unknown base', design({ base: 'aurora' }), 'base'],
    ['no colors', design({ colors: undefined }), 'colors'],
    ['colors as a list', design({ colors: ['#fff'] }), 'colors'],
  ])('rejects %s', (_label, text, key) => {
    const result = parseDesign(text);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.key).toBe(key);
  });

  it('rejects unknown colour names and names them', () => {
    const result = parseDesign(design({ colors: { surface: '#000', background: '#fff', '--gl-fg': '#fff' } }));
    expect(result).toEqual({ ok: false, error: { key: 'unknown_keys', params: { keys: 'background, --gl-fg' } } });
  });

  it.each([['red'], ['rgb(0 0 0)'], ['#12'], ['#1234567'], ['url(x)'], ['#fff; background: url(x)'], [42]])('rejects the value %s', (value) => {
    const result = parseDesign(design({ colors: { surface: value } }));
    expect(result).toEqual({ ok: false, error: { key: 'bad_value', params: { key: 'surface' } } });
  });

  it('accepts #rgb, #rrggbb and #rrggbbaa', () => {
    expect(parseDesign(design({ colors: { fg: '#fff', surface: '#112233', popover: '#11223344' } })).ok).toBe(true);
  });

  it('rejects a file over the size limit', () => {
    const result = parseDesign(design({ pad: 'x'.repeat(21_000) }));
    expect(result.ok ? null : result.error.key).toBe('too_large');
  });
});

describe('applyCustomColors', () => {
  let root: HTMLElement;
  beforeEach(() => {
    root = document.createElement('div');
  });

  it('sets the design colours as custom properties and clears the ones a later design leaves out', () => {
    applyCustomColors({ surface: '#102030', 'line-1': '#abcdef' }, root);
    expect(root.style.getPropertyValue('--gl-surface')).toBe('#102030');
    expect(root.style.getPropertyValue('--line-1')).toBe('#abcdef');

    applyCustomColors({ fg: '#ffffff' }, root);
    expect(root.style.getPropertyValue('--gl-surface')).toBe('');
    expect(root.style.getPropertyValue('--gl-fg')).toBe('#ffffff');

    applyCustomColors(null, root);
    expect(root.getAttribute('style') ?? '').toBe('');
  });

  it('maps tokens to their CSS variables', () => {
    expect(cssVar('field-line')).toBe('--gl-field-line');
    expect(cssVar('line-10')).toBe('--line-10');
    expect(DESIGN_TOKENS).toContain('primary');
  });
});

describe('designTemplate', () => {
  it('writes every token that has a hex value, in a file parseDesign accepts', () => {
    const root = document.createElement('div');
    root.style.setProperty('--gl-surface', '#121416');
    root.style.setProperty('--line-2', '#FF9F43');
    root.style.setProperty('--gl-shadow-card', 'none');
    document.body.append(root);
    const text = designTemplate('Mine', 'light', root);
    root.remove();
    const parsed = parseDesign(text);
    expect(parsed).toEqual({ ok: true, theme: { name: 'Mine', base: 'light', colors: { surface: '#121416', 'line-2': '#ff9f43' } } });
    expect(JSON.parse(text).format).toBe('gravityui-design');
  });
});
