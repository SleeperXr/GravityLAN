import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import MasterTokenRotate from './MasterTokenRotate.vue';
import { api } from '@/api/client';

const { showToast, confirm, copyText } = vi.hoisted(() => ({
  showToast: vi.fn(),
  confirm: vi.fn(),
  copyText: vi.fn(async () => true),
}));

vi.mock('@/api/client', () => ({ api: { rotateMasterToken: vi.fn() } }));
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('@/composables/useConfirm', () => ({ useConfirm: () => ({ confirm }) }));
vi.mock('@/lib/clipboard', () => ({ copyText }));

const TOKEN = 'a'.repeat(64);

async function clickRotate() {
  const wrapper = mount(MasterTokenRotate);
  await wrapper.find('[data-test="rotate-master-token"]').trigger('click');
  await flushPromises();
  return wrapper;
}

describe('MasterTokenRotate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.rotateMasterToken).mockResolvedValue({ token: TOKEN });
  });

  it('shows the new token once after the confirmation', async () => {
    confirm.mockResolvedValue(true);
    const wrapper = await clickRotate();
    expect(api.rotateMasterToken).toHaveBeenCalledOnce();
    expect((wrapper.find('[data-test="master-token-created"] input').element as HTMLInputElement).value).toBe(TOKEN);
  });

  it('replaces nothing when the confirmation is cancelled', async () => {
    confirm.mockResolvedValue(false);
    const wrapper = await clickRotate();
    expect(api.rotateMasterToken).not.toHaveBeenCalled();
    expect(wrapper.find('[data-test="master-token-created"]').exists()).toBe(false);
  });

  it('reports a failure and shows no token', async () => {
    confirm.mockResolvedValue(true);
    vi.mocked(api.rotateMasterToken).mockRejectedValue(new Error('403'));
    const wrapper = await clickRotate();
    expect(showToast).toHaveBeenCalledWith('error', expect.any(String), expect.stringContaining('403'));
    expect(wrapper.find('[data-test="master-token-created"]').exists()).toBe(false);
  });

  it('copies the shown token', async () => {
    confirm.mockResolvedValue(true);
    const wrapper = await clickRotate();
    const copy = wrapper.findAll('[data-test="master-token-created"] button')[0];
    await copy.trigger('click');
    await flushPromises();
    expect(copyText).toHaveBeenCalledWith(TOKEN);
  });
});
