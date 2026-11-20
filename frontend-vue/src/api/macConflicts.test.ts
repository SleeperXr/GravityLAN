import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from './core';

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('MAC conflict API client', () => {
  it('fetches grouped MAC conflicts from GET /api/devices/mac-conflicts', async () => {
    const groups = [
      {
        documented_mac: 'aa:bb:cc:dd:ee:01',
        observed_mac: 'aa:bb:cc:dd:ee:02',
        first_seen: '2026-11-20T08:00:00Z',
        last_seen: '2026-11-20T09:00:00Z',
        devices: [{ id: 4, ip: '192.168.1.10', name: 'nas', source: 'relay' }],
      },
    ];
    fetchMock.mockResolvedValueOnce(jsonResponse(groups));

    const result = await api.getMacConflicts();

    expect(result).toEqual(groups);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/devices/mac-conflicts',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('sends PUT /api/devices/{id}/mac with mac and apply_to_shared', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ changed_device_ids: [4, 5] }));

    const result = await api.setDeviceMac(4, { mac: 'aa-bb-cc-dd-ee-02', apply_to_shared: true });

    expect(result).toEqual({ changed_device_ids: [4, 5] });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/devices/4/mac',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ mac: 'aa-bb-cc-dd-ee-02', apply_to_shared: true }),
      }),
    );
  });

  it('surfaces 422 validation detail as ApiError on invalid MAC', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: 'Not a usable MAC address (six hex pairs, unicast, not all zeros).' }, 422),
    );

    await expect(api.setDeviceMac(4, { mac: 'invalid' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: 'Not a usable MAC address (six hex pairs, unicast, not all zeros).',
    });
  });

  it('sends POST /api/devices/{id}/mac-observations/dismiss and handles 204 and 404', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(api.dismissMacObservation(4, 'aa:bb:cc:dd:ee:02')).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/devices/4/mac-observations/dismiss',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mac: 'aa:bb:cc:dd:ee:02' }),
      }),
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'No such MAC observation for this device' }, 404));
    await expect(api.dismissMacObservation(4, 'aa:bb:cc:dd:ee:99')).rejects.toBeInstanceOf(ApiError);
  });
});
