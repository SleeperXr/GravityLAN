import { type Ref } from 'vue';
import { useEventListener } from '@vueuse/core';

/** Whether a key press lands in something the user is typing into, where "/" must stay a character. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = (target as HTMLInputElement).type;
  return !['button', 'checkbox', 'radio', 'range', 'reset', 'submit', 'color', 'file'].includes(type);
}

/** "/" focuses the page's own filter field (Ctrl+K stays the app-wide search). */
export function useSlashFocus(input: Ref<HTMLInputElement | null>) {
  useEventListener(window, 'keydown', (e: KeyboardEvent) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
    if (isTypingTarget(e.target) || !input.value) return;
    e.preventDefault();
    input.value.focus();
    input.value.select();
  });
}
