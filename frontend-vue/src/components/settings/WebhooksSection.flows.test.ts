import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import WebhooksSection from './WebhooksSection.vue';
import { api } from '@/api/client';
import { t } from '@/i18n';
import type { NotificationOutboxResponse, WebhookSubscriptionResponse } from '@/types';

const { showToast, confirm } = vi.hoisted(() => ({ showToast: vi.fn(), confirm: vi.fn() }));

vi.mock('@/api/client', () => ({
  api: {
    getWebhooks: vi.fn(),
    getOutbox: vi.fn(),
    createWebhook: vi.fn(),
    deleteWebhook: vi.fn(),
    testWebhook: vi.fn(),
    retryOutbox: vi.fn(),
  },
}));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('@/composables/useConfirm', () => ({ useConfirm: () => ({ confirm }) }));

const mocked = vi.mocked(api);

const sub = (extra: Record<string, unknown> = {}) =>
  ({ id: 1, name: 'alerts', url: 'https://example.com/hook', service_type: 'webhook', has_token: false, events: ['device.offline'], ...extra }) as unknown as WebhookSubscriptionResponse;

const entry = (status: string) =>
  ({ id: 9, event_type: 'scan.complete', target_url: 'http://192.0.2.1/hook', service_type: 'webhook', attempts: 3, max_attempts: 3, status, last_error: null, created_at: '2026-11-05T10:00:00Z' }) as unknown as NotificationOutboxResponse;

async function render() {
  const wrapper = mount(WebhooksSection);
  await flushPromises();
  return wrapper;
}
type Section = Awaited<ReturnType<typeof render>>;

const input = (w: Section, label: string) => w.get(`input[aria-label="${label}"]`);
const urlInput = (w: Section) => input(w, t('gv.webhooks.url'));
const nameInput = (w: Section) => input(w, t('gv.webhooks.name'));
const tokenInput = (w: Section) => w.get('input[type="password"]');
const button = (w: Section, text: string) => w.findAll('button').find((b) => b.text().includes(text))!;
const valueOf = (el: { element: Element }) => (el.element as HTMLInputElement).value;
const toastKinds = () => showToast.mock.calls.map((call) => call[0]);
const loads = () => mocked.getWebhooks.mock.calls.length;

async function submit(w: Section) {
  await w.get('form').trigger('submit');
  await flushPromises();
}

async function click(w: Section, text: string) {
  await button(w, text).trigger('click');
  await flushPromises();
}

const deleteFirst = async (w: Section) => {
  await w.get(`button[aria-label="${t('gv.webhooks.btn_delete')}"]`).trigger('click');
  await flushPromises();
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getWebhooks.mockResolvedValue([]);
  mocked.getOutbox.mockResolvedValue([]);
  mocked.createWebhook.mockResolvedValue({} as never);
  mocked.deleteWebhook.mockResolvedValue(undefined as never);
  mocked.testWebhook.mockResolvedValue({} as never);
  mocked.retryOutbox.mockResolvedValue({} as never);
  confirm.mockResolvedValue(true);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('adding a destination', () => {
  it('sends the trimmed form, then empties it and reloads', async () => {
    const w = await render();
    await nameInput(w).setValue('  alerts ');
    await urlInput(w).setValue(' https://example.com/hook ');
    await tokenInput(w).setValue(' placeholder-token ');
    await submit(w);

    expect(mocked.createWebhook).toHaveBeenCalledWith({
      name: 'alerts',
      url: 'https://example.com/hook',
      service_type: 'webhook',
      token: 'placeholder-token',
      events: ['device.offline', 'device.online', 'new_device'],
    });
    expect([valueOf(nameInput(w)), valueOf(urlInput(w)), valueOf(tokenInput(w))]).toEqual(['', '', '']);
    expect(loads()).toBe(2);
    expect(toastKinds()).toEqual(['success']);
  });

  it('leaves out an empty name and token', async () => {
    const w = await render();
    await urlInput(w).setValue('https://example.com/hook');
    await submit(w);
    expect(mocked.createWebhook.mock.calls[0][0]).toMatchObject({ name: undefined, token: undefined });
  });

  it('uses the chosen service', async () => {
    const w = await render();
    await click(w, 'ntfy');
    expect(urlInput(w).attributes('placeholder')).toBe('https://ntfy.sh/topic-name');
    await urlInput(w).setValue('https://ntfy.sh/mine');
    await submit(w);
    expect(mocked.createWebhook.mock.calls[0][0]).toMatchObject({ service_type: 'ntfy' });
  });

  it('adds and removes events by toggling', async () => {
    const w = await render();
    await click(w, t('gv.webhooks.event_scan_complete'));
    await click(w, t('gv.webhooks.event_device_online'));
    await urlInput(w).setValue('https://example.com/hook');
    await submit(w);
    expect(mocked.createWebhook.mock.calls[0][0]).toMatchObject({ events: ['device.offline', 'new_device', 'scan.complete'] });
  });

  it('needs an address', async () => {
    const w = await render();
    await urlInput(w).setValue('   ');
    await submit(w);
    expect(mocked.createWebhook).not.toHaveBeenCalled();
    expect(button(w, t('gv.webhooks.btn_add')).attributes('disabled')).toBeDefined();
  });

  it('needs at least one event', async () => {
    const w = await render();
    await urlInput(w).setValue('https://example.com/hook');
    await click(w, t('gv.webhooks.event_device_offline'));
    await click(w, t('gv.webhooks.event_device_online'));
    await click(w, t('gv.webhooks.event_new_device'));
    await submit(w);
    expect(mocked.createWebhook).not.toHaveBeenCalled();
    expect(button(w, t('gv.webhooks.btn_add')).attributes('disabled')).toBeDefined();
  });

  it('keeps what was typed when the server refuses it', async () => {
    mocked.createWebhook.mockRejectedValue(new Error('blocked target'));
    const w = await render();
    await urlInput(w).setValue('https://example.com/hook');
    await tokenInput(w).setValue('placeholder-token');
    await submit(w);
    expect(showToast).toHaveBeenCalledWith('error', t('common.error'), 'blocked target');
    expect([valueOf(urlInput(w)), valueOf(tokenInput(w))]).toEqual(['https://example.com/hook', 'placeholder-token']);
    expect(loads()).toBe(1);
  });
});

describe('removing a destination', () => {
  beforeEach(() => mocked.getWebhooks.mockResolvedValue([sub()]));

  it('asks by name and does nothing when declined', async () => {
    confirm.mockResolvedValue(false);
    const w = await render();
    await deleteFirst(w);
    expect(confirm.mock.calls[0][0]).toMatchObject({ title: t('gv.webhooks.delete_title', { name: 'alerts' }), danger: true });
    expect(mocked.deleteWebhook).not.toHaveBeenCalled();
  });

  it('falls back to the address for an unnamed destination', async () => {
    mocked.getWebhooks.mockResolvedValue([sub({ name: null })]);
    confirm.mockResolvedValue(false);
    await deleteFirst(await render());
    expect(confirm.mock.calls[0][0]).toMatchObject({ title: t('gv.webhooks.delete_title', { name: 'https://example.com/hook' }) });
  });

  it('deletes once confirmed and reloads', async () => {
    const w = await render();
    await deleteFirst(w);
    expect(mocked.deleteWebhook).toHaveBeenCalledWith(1);
    expect(loads()).toBe(2);
  });

  it('reports a failed delete and does not reload', async () => {
    mocked.deleteWebhook.mockRejectedValue(new Error('nope'));
    const w = await render();
    await deleteFirst(w);
    expect(showToast).toHaveBeenCalledWith('error', t('common.error'), 'nope');
    expect(loads()).toBe(1);
  });
});

describe('sending a test', () => {
  beforeEach(() => mocked.getWebhooks.mockResolvedValue([sub()]));

  it('names the destination and checks the outcome shortly after', async () => {
    const w = await render();
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    await click(w, t('gv.webhooks.btn_test'));
    expect(mocked.testWebhook).toHaveBeenCalledWith('test.event', { status: 'testing', destination: 'alerts', subscription_id: 1 });
    expect(toastKinds()).toEqual(['info']);
    expect(loads()).toBe(1);

    vi.advanceTimersByTime(1500);
    await flushPromises();
    expect(loads()).toBe(2);
  });

  it('can be used again after a failure', async () => {
    mocked.testWebhook.mockRejectedValue(new Error('nope'));
    const w = await render();
    await click(w, t('gv.webhooks.btn_test'));
    expect(showToast).toHaveBeenCalledWith('error', t('common.error'), 'nope');
    expect(button(w, t('gv.webhooks.btn_test')).attributes('disabled')).toBeUndefined();
  });
});

describe('delivery status', () => {
  it.each([
    ['failed', true],
    ['delivered', false],
    ['pending', false],
  ])('a %s entry offers a retry: %s', async (status, offered) => {
    mocked.getOutbox.mockResolvedValue([entry(status)]);
    expect(button(await render(), t('gv.webhooks.btn_retry')) !== undefined).toBe(offered);
  });

  it('retries and reloads', async () => {
    mocked.getOutbox.mockResolvedValue([entry('failed')]);
    const w = await render();
    await click(w, t('gv.webhooks.btn_retry'));
    expect(mocked.retryOutbox).toHaveBeenCalledWith(9);
    expect(loads()).toBe(2);
  });

  it('reports a failed retry', async () => {
    mocked.getOutbox.mockResolvedValue([entry('failed')]);
    mocked.retryOutbox.mockRejectedValue(new Error('nope'));
    const w = await render();
    await click(w, t('gv.webhooks.btn_retry'));
    expect(showToast).toHaveBeenCalledWith('error', t('common.error'), 'nope');
    expect(loads()).toBe(1);
  });
});

describe('loading', () => {
  it('keeps the list on a passing failure', async () => {
    mocked.getWebhooks.mockResolvedValueOnce([sub()]);
    const w = await render();
    expect(w.text()).toContain('https://example.com/hook');

    mocked.getWebhooks.mockRejectedValueOnce(new Error('offline'));
    w.get('h3').element.parentElement!.querySelector('button')!.click();
    await flushPromises();
    expect(mocked.getWebhooks).toHaveBeenCalledTimes(2);
    expect(w.text()).toContain('https://example.com/hook');
    expect(toastKinds()).toEqual([]);
  });
});
