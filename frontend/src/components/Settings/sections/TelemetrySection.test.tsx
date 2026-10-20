import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api, type TelemetryStatus } from '../../../api/client';
import type { Device } from '../../../types';
import { TelemetrySection, formatBytes } from './TelemetrySection';

const showToast = vi.fn();

vi.mock('../../../api/client', () => ({
  api: {
    getTelemetryStatus: vi.fn(),
    updateTelemetryRetention: vi.fn(),
    purgeTelemetry: vi.fn(),
    getDevices: vi.fn(),
  },
}));
vi.mock('../../../context/ToastContext', () => ({ useToast: () => ({ showToast }) }));

const m = vi.mocked(api);

function status(overrides: Partial<TelemetryStatus> = {}): TelemetryStatus {
  const table = (rows: number, oldest: string | null = '2026-10-18T10:00:00') => ({ rows, oldest, newest: null });
  return {
    sizes: { inventory_bytes: 2 * 1024 * 1024, telemetry_bytes: 48 * 1024 * 1024, telemetry_free_bytes: 0 },
    tables: {
      device_health_samples: table(2880),
      device_metrics: table(5760),
      device_health_rollups: table(720, '2026-09-20T00:00:00'),
      device_metrics_rollups: table(0, null),
    },
    retention: { raw_hours: 48, hourly_days: 30, daily_days: 365 },
    limits: {
      raw_hours: { min: 24, max: 720, default: 48 },
      hourly_days: { min: 2, max: 365, default: 30 },
      daily_days: { min: 7, max: 3650, default: 365 },
    },
    ...overrides,
  };
}

const devices = [
  { id: 3, ip: '10.0.0.3', display_name: 'nas', hostname: null },
  { id: 2, ip: '10.0.0.2', display_name: 'router', hostname: null },
] as unknown as Device[];

function renderSection() {
  render(<TelemetrySection />);
  return userEvent.setup();
}

beforeEach(() => {
  vi.clearAllMocks();
  m.getTelemetryStatus.mockResolvedValue(status());
  m.getDevices.mockResolvedValue(devices);
});

describe('TelemetrySection', () => {
  it('shows both database sizes, the stored tiers and the retention', async () => {
    renderSection();
    expect(await screen.findByText('48 MB')).toBeInTheDocument();
    expect(screen.getByText('2.0 MB')).toBeInTheDocument();

    const tiers = screen.getByRole('list', { name: 'Stored measurement data' });
    expect(within(tiers).getByText('Raw data').closest('li')).toHaveTextContent('8,640 entries');
    expect(within(tiers).getByText('Condensed').closest('li')).toHaveTextContent('720 entries');

    expect(screen.getByLabelText('Keep raw data for')).toHaveValue(48);
    expect(screen.getByLabelText('Keep hourly values for')).toHaveValue(30);
    expect(screen.getByLabelText('Keep daily values for')).toHaveValue(365);
    expect(screen.getByText(/\(24–720\)/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save retention' })).not.toBeInTheDocument();
  });

  it('saves a changed retention', async () => {
    m.updateTelemetryRetention.mockResolvedValue(status({ retention: { raw_hours: 72, hourly_days: 30, daily_days: 365 } }));
    const user = renderSection();
    const raw = await screen.findByLabelText('Keep raw data for');
    await waitFor(() => expect(raw).toHaveValue(48));

    await user.clear(raw);
    await user.type(raw, '72');
    await user.click(screen.getByRole('button', { name: 'Save retention' }));

    expect(m.updateTelemetryRetention).toHaveBeenCalledWith({ raw_hours: 72, hourly_days: 30, daily_days: 365 });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Save retention' })).not.toBeInTheDocument());
    expect(showToast).toHaveBeenCalledWith('success', 'Saved', expect.any(String));
  });

  it('reports a rejected retention and can discard it', async () => {
    m.updateTelemetryRetention.mockRejectedValue(new Error('daily_days must be at least hourly_days'));
    const user = renderSection();
    const daily = await screen.findByLabelText('Keep daily values for');
    await waitFor(() => expect(daily).toHaveValue(365));

    await user.clear(daily);
    await user.type(daily, '10');
    await user.click(screen.getByRole('button', { name: 'Save retention' }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(
      'error', 'Error', expect.stringContaining('daily_days must be at least hourly_days'),
    ));

    await user.click(screen.getByRole('button', { name: 'Discard' }));
    expect(daily).toHaveValue(365);
  });

  it('deletes everything only on the second click', async () => {
    m.purgeTelemetry.mockResolvedValue({
      ...status({ sizes: { inventory_bytes: 2 * 1024 * 1024, telemetry_bytes: 1024 * 1024, telemetry_free_bytes: 0 } }),
      deleted: { device_health_samples: 2880, device_metrics: 5760, device_health_rollups: 720, device_metrics_rollups: 0 },
    });
    const user = renderSection();
    await screen.findByText('48 MB');

    await user.click(screen.getByRole('button', { name: 'Delete everything' }));
    expect(m.purgeTelemetry).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Really? Click again' }));

    expect(m.purgeTelemetry).toHaveBeenCalledWith({ scope: 'all' });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(
      'success', 'Measurement data deleted', '9,360 entries deleted, 47 MB freed.',
    ));
    expect(await screen.findByText('1.0 MB')).toBeInTheDocument();
  });

  it('deletes data older than the given number of days', async () => {
    m.purgeTelemetry.mockResolvedValue({ ...status(), deleted: {} });
    const user = renderSection();
    const days = await screen.findByLabelText('Age in days');

    await user.clear(days);
    await user.type(days, '90');
    await user.click(screen.getByRole('button', { name: 'Delete older' }));
    await user.click(screen.getByRole('button', { name: 'Really? Click again' }));

    expect(m.purgeTelemetry).toHaveBeenCalledWith({ scope: 'older_than', older_than_days: 90 });
  });

  it('deletes the data of the chosen device', async () => {
    m.purgeTelemetry.mockResolvedValue({ ...status(), deleted: {} });
    const user = renderSection();
    const button = await screen.findByRole('button', { name: 'Delete device data' });
    expect(button).toBeDisabled();

    const select = screen.getByLabelText('Device');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(3));
    // Sorted by name
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(
      ['Choose a device …', 'nas (10.0.0.3)', 'router (10.0.0.2)'],
    );
    await user.selectOptions(select, '2');
    await user.click(button);
    await user.click(screen.getByRole('button', { name: 'Really? Click again' }));

    expect(m.purgeTelemetry).toHaveBeenCalledWith({ scope: 'device', device_id: 2 });
  });

  it('reports a failed purge', async () => {
    m.purgeTelemetry.mockRejectedValue(new Error('locked'));
    const user = renderSection();
    await screen.findByText('48 MB');

    await user.click(screen.getByRole('button', { name: 'Delete everything' }));
    await user.click(screen.getByRole('button', { name: 'Really? Click again' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('error', 'Error', 'Delete failed: locked'));
  });
});

describe('formatBytes', () => {
  it('picks a readable unit', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(48 * 1024 * 1024)).toBe('48 MB');
  });
});
