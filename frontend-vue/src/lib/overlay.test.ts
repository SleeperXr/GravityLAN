import { afterEach, describe, expect, it } from 'vitest';
import { TOAST_REGION_ATTR, isPasswordManagerOrExtensionElement, keepOpenForPopups } from './overlay';

function add(html: string): Element {
  const host = document.createElement('div');
  host.innerHTML = html;
  document.body.appendChild(host);
  return host.firstElementChild!;
}

/** What reka-ui hands an outside handler: the event itself, with the original pointer event inside */
function outsideEvent(target: Element): Event {
  const original = new MouseEvent('pointerdown', { bubbles: true });
  Object.defineProperty(original, 'target', { value: target });
  const event = new CustomEvent('dismissableLayer.pointerDownOutside', { cancelable: true, detail: { originalEvent: original } });
  Object.defineProperty(event, 'target', { value: target });
  return event;
}

const keptOpen = (target: Element) => {
  const event = outsideEvent(target);
  keepOpenForPopups(event);
  return event.defaultPrevented;
};

afterEach(() => {
  document.body.innerHTML = '';
  document.body.className = '';
  document.documentElement.className = '';
  document.documentElement.removeAttribute('id');
});

describe('isPasswordManagerOrExtensionElement', () => {
  it.each([
    ['a known element of an extension', '<bitwarden-notification-bar></bitwarden-notification-bar>'],
    ['a class naming a password manager', '<div class="lastpass-popup"></div>'],
    ['an id naming a password manager', '<div id="onepassword-menu"></div>'],
    ['an extension frame', '<iframe src="chrome-extension://abc/menu.html"></iframe>'],
    ['a frame titled for Bitwarden', '<iframe title="Bitwarden autofill"></iframe>'],
    ['something inside such an element', '<div class="dashlane-root"><button>x</button></div>'],
  ])('recognises %s', (_name, html) => {
    const el = add(html);
    expect(isPasswordManagerOrExtensionElement(el.querySelector('button') ?? el)).toBe(true);
  });

  it('ignores ordinary page content', () => {
    expect(isPasswordManagerOrExtensionElement(add('<button class="btn">Save</button>'))).toBe(false);
    expect(isPasswordManagerOrExtensionElement(add('<iframe src="https://example.com"></iframe>'))).toBe(false);
  });

  it('does not count the page itself, whatever an extension marks on it', () => {
    document.documentElement.className = 'bitwarden-active';
    document.body.className = 'keepass-helper';
    const button = add('<button>Save</button>');
    expect(isPasswordManagerOrExtensionElement(button)).toBe(false);
    expect(isPasswordManagerOrExtensionElement(document.body)).toBe(false);
    expect(isPasswordManagerOrExtensionElement(document.documentElement)).toBe(false);
  });
});

describe('keepOpenForPopups', () => {
  it('keeps the panel open for a toast', () => {
    expect(keptOpen(add(`<section ${TOAST_REGION_ATTR}><button>x</button></section>`).querySelector('button')!)).toBe(true);
  });

  it('keeps the panel open for a password manager popup', () => {
    expect(keptOpen(add('<div class="bitwarden-notification-bar"><button>x</button></div>').querySelector('button')!)).toBe(true);
  });

  it('keeps the panel open when the popup sits in a shadow root', () => {
    const host = add('<bitwarden-inline-menu></bitwarden-inline-menu>');
    const inner = host.attachShadow({ mode: 'open' }).appendChild(document.createElement('button'));
    const event = new CustomEvent('outside', { cancelable: true });
    Object.defineProperty(event, 'target', { value: host.ownerDocument.body });
    Object.defineProperty(event, 'composedPath', { value: () => [inner, host, document.body, document.documentElement, document] });
    keepOpenForPopups(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it('lets a click on the page close the panel', () => {
    expect(keptOpen(add('<button>elsewhere</button>'))).toBe(false);
  });

  it('lets a click on the page close the panel even when an extension marked the page', () => {
    document.body.className = 'bitwarden-active';
    document.documentElement.id = 'lastpass-root';
    const button = add('<button>elsewhere</button>');
    const event = outsideEvent(button);
    Object.defineProperty(event, 'composedPath', { value: () => [button, button.parentElement, document.body, document.documentElement, document] });
    keepOpenForPopups(event);
    expect(event.defaultPrevented).toBe(false);
  });
});
