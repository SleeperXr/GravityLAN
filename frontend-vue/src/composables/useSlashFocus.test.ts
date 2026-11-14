import { describe, expect, it } from 'vitest';
import { isTypingTarget } from './useSlashFocus';

const el = (html: string) => {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host.firstElementChild as HTMLElement;
};

describe('isTypingTarget', () => {
  it('treats text fields, text areas, selects and editable content as typing', () => {
    expect(isTypingTarget(el('<input type="text">'))).toBe(true);
    expect(isTypingTarget(el('<input type="search">'))).toBe(true);
    expect(isTypingTarget(el('<input>'))).toBe(true);
    expect(isTypingTarget(el('<textarea></textarea>'))).toBe(true);
    expect(isTypingTarget(el('<select></select>'))).toBe(true);
    const editable = el('<div contenteditable="true"></div>');
    Object.defineProperty(editable, 'isContentEditable', { value: true });
    expect(isTypingTarget(editable)).toBe(true);
  });

  it('leaves buttons, checkboxes and plain elements to the shortcut', () => {
    expect(isTypingTarget(el('<input type="checkbox">'))).toBe(false);
    expect(isTypingTarget(el('<button></button>'))).toBe(false);
    expect(isTypingTarget(el('<div></div>'))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});
