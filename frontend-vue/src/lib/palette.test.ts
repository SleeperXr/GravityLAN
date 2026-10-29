import { describe, expect, it } from 'vitest';
import { linePaletteHex, nextPaletteColour } from './palette';

const palette = ['#2ec4a6', '#ff9f43', '#5aa9ff'];

describe('line palette', () => {
  it('reads the hex slots of the theme and skips the rest', () => {
    const root = document.createElement('div');
    root.style.setProperty('--line-1', '#2ec4a6');
    root.style.setProperty('--line-2', 'oklch(70% 0.1 200)');
    root.style.setProperty('--line-3', ' #5AA9FF ');
    document.body.append(root);
    expect(linePaletteHex(root)).toEqual(['#2ec4a6', '#5AA9FF']);
    root.remove();
  });

  it('gives a new area the first palette colour nobody uses', () => {
    expect(nextPaletteColour([], palette)).toBe('#2ec4a6');
    expect(nextPaletteColour(['#2EC4A6'], palette)).toBe('#ff9f43');
  });

  it('starts over once every colour is used', () => {
    expect(nextPaletteColour([...palette, '#123456'], palette)).toBe('#ff9f43');
  });

  it('has nothing to give without a palette', () => {
    expect(nextPaletteColour([], [])).toBe('');
  });
});
