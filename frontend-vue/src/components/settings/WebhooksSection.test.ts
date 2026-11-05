import { describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import WebhooksSection from './WebhooksSection.vue';
import { api } from '@/api/client';
import type { NotificationOutboxResponse } from '@/types';

vi.mock('@/api/client', () => ({
  api: { getWebhooks: vi.fn(async () => []), getOutbox: vi.fn(async () => []) },
}));

const entries = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    event_type: 'scan.complete',
    target_url: 'http://192.0.2.1/hook',
    service_type: 'webhook',
    attempts: 3,
    max_attempts: 3,
    status: 'failed',
    last_error: 'All connection attempts failed',
    created_at: '2026-11-05T10:00:00Z',
  })) as unknown as NotificationOutboxResponse[];

async function render(count: number) {
  vi.mocked(api.getOutbox).mockResolvedValue(entries(count));
  const wrapper = mount(WebhooksSection);
  await flushPromises();
  return wrapper;
}

const rows = (wrapper: Awaited<ReturnType<typeof render>>) => wrapper.find('[data-test="outbox-list"]').element.children.length;

describe('WebhooksSection outbox', () => {
  it('shows the newest five and the rest on request', async () => {
    const wrapper = await render(20);
    expect(rows(wrapper)).toBe(5);

    const toggle = wrapper.find('button[aria-expanded]');
    await toggle.trigger('click');
    expect(rows(wrapper)).toBe(20);
    expect(toggle.attributes('aria-expanded')).toBe('true');

    await toggle.trigger('click');
    expect(rows(wrapper)).toBe(5);
  });

  it('needs no toggle for a short list', async () => {
    const wrapper = await render(5);
    expect(rows(wrapper)).toBe(5);
    expect(wrapper.find('button[aria-expanded]').exists()).toBe(false);
  });
});
