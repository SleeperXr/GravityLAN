/** Marks the toast region; overlays treat clicks inside it as their own. */
export const TOAST_REGION_ATTR = 'data-gl-toasts';

/** Popups and inline menus that password managers and other extensions put into the page */
const EXTENSION_SELECTOR = [
  'bitwarden-notification-bar',
  '[id*="bitwarden" i]',
  '[class*="bitwarden" i]',
  '[data-bitwarden]',
  '[id*="1password" i]',
  '[class*="1password" i]',
  '[id*="onepassword" i]',
  '[class*="onepassword" i]',
  '[id*="lastpass" i]',
  '[class*="lastpass" i]',
  '[id*="dashlane" i]',
  '[class*="dashlane" i]',
  '[id*="keepass" i]',
  '[class*="keepass" i]',
  'iframe[src*="extension:" i]',
  'iframe[src*="bitwarden" i]',
].join(',');

const EXTENSION_TAGS = ['bitwarden', '1password', 'onepassword', 'lastpass', 'dashlane', 'keepass'];

/** `<html>` and `<body>`: an extension may mark them, and that must not turn every click into one on a popup. */
function isPageRoot(el: Element): boolean {
  return el === el.ownerDocument.body || el === el.ownerDocument.documentElement;
}

function isExtensionFrame(el: Element): boolean {
  if (el.tagName !== 'IFRAME') return false;
  const src = el.getAttribute('src') ?? '';
  return /^(chrome|moz|safari-web)?-?extension:/i.test(src) || /bitwarden/i.test(src) || /bitwarden/i.test(el.getAttribute('title') ?? '');
}

/** True for an element of a password manager or extension popup, or anything inside one (below `<body>`). */
export function isPasswordManagerOrExtensionElement(el: Element): boolean {
  if (isPageRoot(el)) return false;
  const marked = el.closest(EXTENSION_SELECTOR);
  if (marked && !isPageRoot(marked)) return true;
  const tag = el.tagName.toLowerCase();
  return EXTENSION_TAGS.some((name) => tag.includes(name)) || isExtensionFrame(el);
}

/** Whether a node belongs to a toast or to a popup an extension put over the page. */
function belongsToPopup(node: EventTarget | null | undefined): boolean {
  if (!(node instanceof Element)) return false;
  return Boolean(node.closest(`[${TOAST_REGION_ATTR}]`)) || isPasswordManagerOrExtensionElement(node);
}

/** The event's target and path, and those of the pointer event reka-ui wraps (also inside shadow roots). */
function nodesOf(event: Event): (EventTarget | null | undefined)[] {
  const original = (event as CustomEvent<{ originalEvent?: Event }>).detail?.originalEvent;
  return [
    event.target,
    original?.target,
    ...(typeof event.composedPath === 'function' ? event.composedPath() : []),
    ...(typeof original?.composedPath === 'function' ? original.composedPath() : []),
  ];
}

/** True when an outside interaction is with a toast or an extension popup, so the sheet or dialog stays open. */
export function shouldKeepOverlayOpen(event: Event): boolean {
  return nodesOf(event).some(belongsToPopup);
}

/**
 * For reka-ui's `interactOutside` / `pointerDownOutside` on a dialog or sheet: closing a toast (or using its
 * action) or using a password manager's popup (Bitwarden, 1Password, ...) is not a click outside, so it must
 * not close the panel.
 */
export function keepOpenForPopups(event: Event): void {
  if (shouldKeepOverlayOpen(event)) event.preventDefault();
}
