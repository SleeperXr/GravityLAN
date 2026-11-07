/** Marks the toast region; overlays treat clicks inside it as their own. */
export const TOAST_REGION_ATTR = 'data-gl-toasts';

/**
 * For reka-ui's `interactOutside` on a dialog or sheet: closing a toast (or using its action) is not a
 * click outside, so it must not close the panel the toast reports on.
 */
export function keepOpenForToasts(event: Event): void {
  const target = event.target;
  if (target instanceof Element && target.closest(`[${TOAST_REGION_ATTR}]`)) event.preventDefault();
}
