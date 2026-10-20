import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { RouterImportPreview, RouterNetworkPreview, RouterSource } from '../../../types';
import { api } from '../../../api/client';
import { RouterImportPanel } from './RouterImportPanel';

const showToast = vi.fn();

vi.mock('../../../api/client', () => ({
  api: {
    getRouterSources: vi.fn(), deleteRouterSource: vi.fn(),
    previewRouterImport: vi.fn(), applyRouterImport: vi.fn(),
  },
}));
vi.mock('../../../context/ToastContext', () => ({ useToast: () => ({ showToast }) }));

const m = vi.mocked(api);

const net = (cidr: string, extra: Partial<RouterNetworkPreview>): RouterNetworkPreview => ({
  cidr, name: null, gateway_ip: null, vlan_id: null, interface: null, status: 'new', fills: [], existing_name: null, ...extra,
});

const okPreview: RouterImportPreview = {
  status: 'ok',
  provider: 'snmp',
  host: '192.168.1.1',
  networks: [
    net('192.168.1.0/24', { name: 'br0', gateway_ip: '192.168.1.1', status: 'exists', existing_name: 'Home' }),
    net('192.168.10.0/24', { name: 'Kameras', gateway_ip: '192.168.10.1', vlan_id: 10, status: 'update', fills: ['gateway_ip', 'vlan_id'], existing_name: 'Cams' }),
    net('192.168.20.0/24', { name: 'IoT', gateway_ip: '192.168.20.1', vlan_id: 20, interface: 'br20' }),
    net('10.0.0.0/8', { gateway_ip: '10.0.0.1', status: 'too_large' }),
  ],
};

function renderPanel(onApplied = vi.fn()) {
  render(<RouterImportPanel onApplied={onApplied} />);
  return { user: userEvent.setup(), onApplied };
}

beforeEach(() => {
  vi.clearAllMocks();
  m.getRouterSources.mockResolvedValue([]);
  m.previewRouterImport.mockResolvedValue(okPreview);
  m.applyRouterImport.mockResolvedValue({ added: ['192.168.20.0/24'], updated: ['192.168.10.0/24'], unchanged: [] });
  m.deleteRouterSource.mockResolvedValue({ status: 'ok' });
});

describe('RouterImportPanel', () => {
  it('fetches over SNMP and pre-selects only what adds something', async () => {
    const { user } = renderPanel();
    await user.type(screen.getByLabelText('Router address'), '192.168.1.1');
    await user.type(screen.getByLabelText('Community'), 'public');
    await user.click(screen.getByRole('button', { name: 'Fetch' }));

    expect(m.previewRouterImport).toHaveBeenCalledWith({
      provider: 'snmp', host: '192.168.1.1', port: null, options: {}, secrets: { community: 'public' },
    });
    const list = await screen.findByRole('list', { name: 'Networks from the router' });
    expect(within(list).getByLabelText('Add 192.168.20.0/24')).toBeChecked();
    expect(within(list).getByLabelText('Add 192.168.10.0/24')).toBeChecked();
    expect(within(list).getByLabelText('Add 192.168.1.0/24')).toBeDisabled();
    expect(within(list).getByLabelText('Add 10.0.0.0/8')).toBeDisabled();
    expect(within(list).getByText('exists as "Cams" – fills in Gateway, VLAN')).toBeInTheDocument();
    expect(within(list).getByText('already configured as "Home"')).toBeInTheDocument();
    expect(within(list).getByText('too large to scan (larger than /16)')).toBeInTheDocument();
    // The typed secret is not kept in the form after a successful fetch
    expect(screen.getByLabelText('Community')).toHaveValue('');
  });

  it('applies only the picked networks and reloads the subnets', async () => {
    const { user, onApplied } = renderPanel();
    await user.type(screen.getByLabelText('Router address'), '192.168.1.1');
    await user.click(screen.getByRole('button', { name: 'Fetch' }));
    await user.click(await screen.findByLabelText('Add 192.168.10.0/24'));
    await user.click(screen.getByRole('button', { name: 'Apply (1)' }));

    expect(m.applyRouterImport).toHaveBeenCalledWith([
      { cidr: '192.168.20.0/24', name: 'IoT', gateway_ip: '192.168.20.1', vlan_id: 20 },
    ]);
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    expect(showToast).toHaveBeenCalledWith('success', expect.any(String), '1 network(s) added, 1 completed.');
    expect(screen.queryByRole('list', { name: 'Networks from the router' })).not.toBeInTheDocument();
  });

  it('asks to confirm the UniFi certificate, then fetches with the pinned fingerprint', async () => {
    const fingerprint = Array(32).fill('AB').join(':');
    m.previewRouterImport
      .mockResolvedValueOnce({ status: 'confirm_certificate', provider: 'unifi', host: '192.168.1.1', networks: [], fingerprint, reason: 'untrusted_certificate' })
      .mockResolvedValueOnce({ ...okPreview, provider: 'unifi' });
    const { user } = renderPanel();
    await user.selectOptions(screen.getByLabelText('Ask via'), 'unifi');
    await user.type(screen.getByLabelText('Router address'), '192.168.1.1');
    await user.type(screen.getByLabelText('API key'), 'my-key');
    await user.click(screen.getByRole('button', { name: 'Fetch' }));

    expect(await screen.findByText(fingerprint)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Trust fingerprint and fetch' }));

    expect(m.previewRouterImport).toHaveBeenLastCalledWith({
      provider: 'unifi', host: '192.168.1.1', port: null, options: { fingerprint }, secrets: { api_key: 'my-key' },
    });
    expect(await screen.findByRole('list', { name: 'Networks from the router' })).toBeInTheDocument();
    expect(screen.getByLabelText('Certificate fingerprint (SHA-256)')).toHaveValue(fingerprint);
  });

  it('shows why a fetch failed', async () => {
    m.previewRouterImport.mockRejectedValue(new Error('8.8.8.8 is not a private LAN address.'));
    const { user } = renderPanel();
    await user.type(screen.getByLabelText('Router address'), '8.8.8.8');
    await user.click(screen.getByRole('button', { name: 'Fetch' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Fetch failed: 8.8.8.8 is not a private LAN address.');
    expect(m.applyRouterImport).not.toHaveBeenCalled();
  });

  it('prefills a saved connection, keeps stored secrets and can forget them', async () => {
    const saved: RouterSource[] = [{
      provider: 'snmp', host: '192.168.1.1', port: 1161, options: { version: '2c' }, stored_secrets: ['community'],
    }];
    m.getRouterSources.mockResolvedValueOnce(saved).mockResolvedValueOnce(saved).mockResolvedValue([]);
    const { user } = renderPanel();

    await waitFor(() => expect(screen.getByLabelText('Router address')).toHaveValue('192.168.1.1'));
    expect(screen.getByLabelText('Port')).toHaveValue(1161);
    expect(screen.getByLabelText('Community')).toHaveAttribute('placeholder', 'stored – leave empty to keep it');

    await user.click(screen.getByRole('button', { name: 'Fetch' }));
    expect(m.previewRouterImport).toHaveBeenCalledWith(expect.objectContaining({ port: 1161, secrets: {} }));

    await user.click(await screen.findByRole('button', { name: 'Delete stored credentials' }));
    expect(m.deleteRouterSource).toHaveBeenCalledWith('snmp');
    await waitFor(() => expect(screen.getByLabelText('Router address')).toHaveValue(''));
  });

  it('shows the SNMPv3 fields', async () => {
    const { user } = renderPanel();
    await user.selectOptions(screen.getByLabelText('SNMP version'), '3');
    expect(screen.queryByLabelText('Community')).not.toBeInTheDocument();
    for (const label of ['User', 'Authentication', 'Auth password', 'Encryption', 'Privacy password (empty = none)']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });
});
