import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { ApiError, api } from '@/api/core';
import DataSections from './DataSections.vue';

const showToast = vi.fn();

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast }),
}));

vi.mock('@/composables/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true) }),
}));

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('Backup export client & DataSections error handling', () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    createObjectURL = vi.fn(() => 'blob:backup-url');
    revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    showToast.mockReset();
    fetchMock.mockReset();
  });

  afterEach(() => {
    clickSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('api.exportBackup propagates HTTP 500 JSON detail as ApiError', async () => {
    const detail = 'Backup export failed: the database could not be read completely, so no backup file was created.';
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail }, 500));

    await expect(api.exportBackup()).rejects.toMatchObject({
      name: 'ApiError',
      status: 500,
      message: detail,
    });
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail }, 500));
    await expect(api.exportBackup()).rejects.toBeInstanceOf(ApiError);
  });

  it('triggers a JSON backup download on HTTP 200', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ metadata: { version: '0.8.0' }, devices: [{ id: 1, ip: '10.0.0.1' }] }, 200),
    );

    const wrapper = mount(DataSections);
    await wrapper.find('#backup button').trigger('click');
    await flushPromises();

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:backup-url');
    expect(showToast).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('shows an error toast and triggers no download on HTTP 500 JSON with detail', async () => {
    const detail = 'Backup export failed: the database could not be read completely, so no backup file was created.';
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail }, 500));

    const wrapper = mount(DataSections);
    await wrapper.find('#backup button').trigger('click');
    await flushPromises();

    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith('error', expect.any(String), expect.stringContaining(detail));
    wrapper.unmount();
  });
});
