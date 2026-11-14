"""Proxmox API contracts, credential handling, and safe IP-to-name enrichment."""
import asyncio
import ipaddress
import json
import ssl
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.models.device import Device, DiscoveredHost
from app.models.proxmox import ProxmoxIntegration
import app.services.proxmox as proxmox_service
from app.services.proxmox import Guest, ProxmoxClient, ProxmoxError, apply_guests, sync_lock, sync_proxmox
from app.services.secret_vault import vault


async def test_discover_vm_lxc_static_and_partial_failure():
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'PVEAPIToken=reader@pve!inventory=secret'
        path = request.url.path
        if path.endswith('/cluster/resources'):
            data = [
                {'node': 'pve', 'vmid': i, 'type': kind, 'name': name, 'status': state}
                for i, kind, name, state in [(100, 'qemu', 'nas', 'running'), (101, 'lxc', 'dns', 'running'),
                                             (102, 'lxc', 'stopped', 'stopped'), (103, 'qemu', 'no-agent', 'running'),
                                             (104, 'qemu', 'off', 'stopped')]
            ]
        elif path.endswith('/100/agent/network-get-interfaces'):
            data = {'result': [{'name': 'lo', 'ip-addresses': [{'ip-address': '127.0.0.1'}]},
                               {'name': 'ens18', 'ip-addresses': [{'ip-address': '192.168.1.10'},
                                {'ip-address': 'fe80::1'}, {'ip-address': 'fd00::10'}]}]}
        elif path.endswith('/101/interfaces'):
            data = [{'name': 'eth0', 'inet': '192.168.1.11/24', 'inet6': '::/0',
                     'ip-addresses': [{'ip-address': '192.168.1.11'}, {'ip-address': 'fd00::11'}]},
                    {'name': 'lo', 'inet': '127.0.0.1/8'}]
        elif path.endswith('/102/config'):
            data = {'net0': 'name=eth0,ip=192.168.1.12/24,ip6=auto', 'net1': 'name=eth1,ip=dhcp'}
        else:
            return httpx.Response(500, json={'message': 'agent unavailable'})
        return httpx.Response(200, json={'data': data})

    async with ProxmoxClient('https://pve:8006', 'reader@pve!inventory', 'secret') as client:
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url='https://pve:8006/api2/json/',
                                        headers={'Authorization': 'PVEAPIToken=reader@pve!inventory=secret'},
                                        transport=httpx.MockTransport(handle))
        guests, skipped = await client.discover()
    assert {g.name: g.addresses for g in guests} == {
        'nas': ['192.168.1.10', 'fd00::10'], 'dns': ['192.168.1.11', 'fd00::11'], 'stopped': ['192.168.1.12']}
    assert {(x.identity, x.reason) for x in skipped} == {('qemu/103', 'unreadable'), ('qemu/104', 'vm_stopped')}
    assert all(r.method == 'GET' for r in requests)
    assert not any('/104/' in r.url.path for r in requests)


@pytest.mark.parametrize('status', [301, 401, 403, 500])
async def test_errors_do_not_expose_remote_content_or_follow_redirects(status):
    async with ProxmoxClient('https://pve', 'reader@pve!inventory', 'secret') as client:
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url='https://pve/api2/json/', transport=httpx.MockTransport(
            lambda r: httpx.Response(status, text='sensitive remote content', headers={'Location': 'https://other-host'})))
        with pytest.raises(ProxmoxError) as error:
            await client.discover()
        assert 'sensitive' not in str(error.value)


async def test_real_self_signed_tls_requires_explicit_opt_out(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1)).add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)

    async def respond(reader, writer):
        try:
            await reader.readuntil(b'\r\n\r\n')
            body = b'{"data": []}'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
                         + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, '127.0.0.1', 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    async with server:
        async with ProxmoxClient(f'https://127.0.0.1:{port}', 'reader@pve!inventory', 'secret') as client:
            with pytest.raises(ProxmoxError, match='TLS'):
                await client.discover()
        async with ProxmoxClient(f'https://127.0.0.1:{port}', 'reader@pve!inventory', 'secret', verify_tls=False) as client:
            assert await client.discover() == ([], [])


async def test_enrichment_preserves_custom_names_and_reachability(db):
    connection = ProxmoxIntegration(id=1)
    last_seen = datetime(2020, 1, 1)
    automatic = Device(ip='192.168.1.10', display_name='192.168.1.10', is_online=False, last_seen=last_seen)
    custom = Device(ip='192.168.1.11', hostname='old', display_name='My DNS', is_online=True)
    custom_discovery = DiscoveredHost(ip='192.168.1.11', custom_name='Custom alias', last_seen=last_seen)
    db.add_all([connection, automatic, custom, custom_discovery])
    await db.commit()
    result = await apply_guests(db, connection, [Guest('qemu/100', 'nas', ['192.168.1.10']),
                                               Guest('lxc/101', 'dns', ['192.168.1.11', '192.168.1.12'])])
    assert result['addresses'] == 3
    assert automatic.display_name == 'nas'
    assert automatic.is_online is False
    assert automatic.last_seen == last_seen
    assert custom.display_name == 'My DNS' and custom.hostname == 'old'
    assert custom_discovery.custom_name == 'Custom alias'
    assert custom_discovery.last_seen == last_seen
    discovered = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == '192.168.1.12'))).scalar_one()
    assert discovered.hostname == 'dns' and discovered.is_online is False
    await apply_guests(db, connection, [Guest('qemu/100', 'renamed-nas', ['192.168.1.10'])])
    assert automatic.display_name == 'renamed-nas'
    automatic.display_name = 'My renamed server'
    await db.commit()  # A manual rename is saved in its own request.
    await apply_guests(db, connection, [Guest('qemu/100', 'nas-again', ['192.168.1.10'])])
    assert automatic.display_name == 'My renamed server'


async def test_duplicate_ips_are_not_assigned_to_arbitrary_guests(db):
    connection = ProxmoxIntegration(id=1)
    db.add(connection)
    result = await apply_guests(db, connection, [Guest('qemu/100', 'a', ['192.168.1.10']),
                                               Guest('lxc/101', 'b', ['192.168.1.10'])])
    assert result['addresses'] == 0 and result['conflicts'] == 1
    assert (await db.execute(select(DiscoveredHost))).scalars().all() == []


async def test_settings_encrypt_secret_retain_it_and_require_reentry_for_new_target(client, db, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    payload = {'enabled': True, 'url': 'https://pve:8006/api2/json/', 'token_id': 'reader@pve!inventory',
               'token_secret': 'secret-value'}
    response = await client.put('/api/settings/proxmox', json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['url'] == 'https://pve:8006'
    assert response.json()['verify_tls'] is True
    assert 'secret-value' not in response.text and 'encrypted_secret' not in response.text
    connection = await db.get(ProxmoxIntegration, 1)
    assert connection.encrypted_secret != 'secret-value'
    assert vault.decrypt(connection.encrypted_secret) == 'secret-value'
    assert 'proxmox' not in (await client.get('/api/settings', headers=headers)).text
    payload.pop('token_secret')
    response = await client.put('/api/settings/proxmox', json=payload | {'verify_tls': False}, headers=headers)
    assert response.json()['verify_tls'] is False
    assert vault.decrypt(connection.encrypted_secret) == 'secret-value'
    response = await client.put('/api/settings/proxmox', json=payload | {'url': 'https://other'}, headers=headers)
    assert response.status_code == 400
    assert connection.url == 'https://pve:8006'
    assert (await client.delete('/api/settings/proxmox', headers=headers)).status_code == 204
    assert await db.get(ProxmoxIntegration, 1) is None


@pytest.mark.parametrize('url', ['http://pve:8006', 'https://user:pass@pve', 'https://pve/other', 'https://pve?token=x'])
async def test_invalid_urls_rejected(client, admin_token, url):
    response = await client.put('/api/settings/proxmox', json={'url': url},
                                headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 422


async def test_no_unauthenticated_or_readonly_mutations(client, admin_token):
    assert (await client.get('/api/settings/proxmox')).status_code == 401
    token = (await client.post('/api/auth/tokens', json={'name': 'reader'},
                              headers={'Authorization': f'Bearer {admin_token}'})).json()['token']
    for method, path, payload in [('PUT', '', {}), ('POST', '/sync', None), ('DELETE', '', None)]:
        response = await client.request(method, '/api/settings/proxmox' + path, json=payload,
                                        headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 403


async def test_failed_sync_preserves_previous_inventory_and_records_safe_error(db, monkeypatch):
    connection = ProxmoxIntegration(id=1, enabled=True, url='https://pve', token_id='reader@pve!inventory',
                                     encrypted_secret=vault.encrypt('secret'), inventory='{"old": {}}')
    db.add(connection)
    await db.commit()

    async def fail(self):
        raise ProxmoxError('Proxmox denied access. Check the API token and its permissions.')
    monkeypatch.setattr(ProxmoxClient, 'discover', fail)
    with pytest.raises(ProxmoxError):
        await sync_proxmox(db)
    assert json.loads(connection.inventory) == {'old': {}}
    assert 'denied access' in connection.last_error


async def test_manual_sync_updates_names_visible_through_device_api(client, db, admin_token, monkeypatch):
    import app.api.scanner as scanner_api

    @asynccontextmanager
    async def test_session():
        yield db
    monkeypatch.setattr(scanner_api, 'async_session', test_session)
    headers = {'Authorization': f'Bearer {admin_token}'}
    db.add(Device(ip='192.168.1.10', display_name='192.168.1.10'))
    await db.commit()
    response = await client.put('/api/settings/proxmox', headers=headers, json={
        'enabled': True, 'url': 'https://pve:8006', 'token_id': 'reader@pve!inventory', 'token_secret': 'secret'})
    assert response.status_code == 200

    async def discover(self):
        return ([Guest('qemu/100', 'proxmox-nas', ['192.168.1.10']), Guest('lxc/101', 'proxmox-dns', ['192.168.1.11'])],
                [proxmox_service.Skipped('qemu/102', 'off', 'vm_stopped')])
    monkeypatch.setattr(ProxmoxClient, 'discover', discover)
    response = await client.post('/api/settings/proxmox/sync', headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {'guests': 2, 'addresses': 2, 'updated_devices': 1, 'skipped': 1, 'conflicts': 0, 'outside': 0}
    report = (await client.get('/api/settings/proxmox/report', headers=headers)).json()['report']
    assert report['skipped'] == [{'guest': 'qemu/102', 'name': 'off', 'reason': 'vm_stopped'}]
    assert [a['status'] for g in report['guests'] for a in g['addresses']] == ['new_host', 'renamed']
    devices = (await client.get('/api/devices', headers=headers)).json()
    assert devices[0]['display_name'] == 'proxmox-nas'
    hosts = (await client.get('/api/scanner/discovered', headers=headers)).json()
    assert any(h['ip'] == '192.168.1.11' and h['hostname'] == 'proxmox-dns' for h in hosts)
    settings = (await client.get('/api/settings/proxmox', headers=headers)).json()
    assert settings['last_sync'] and settings['last_error'] is None


async def test_sync_rejects_overlapping_request(client, admin_token):
    async with sync_lock:
        response = await client.post('/api/settings/proxmox/sync', headers={'Authorization': f'Bearer {admin_token}'})
    assert response.status_code == 409


async def test_planner_keeps_imported_guests_when_network_probe_misses(db):
    from app.scanner.planner import _cleanup_discovered_hosts
    db.add(ProxmoxIntegration(id=1, enabled=True, inventory=json.dumps({'192.168.1.10': {'name': 'nas'}})))
    host = DiscoveredHost(ip='192.168.1.10', hostname='nas', is_online=True, is_monitored=False)
    db.add(host)
    await db.commit()
    await _cleanup_discovered_hosts(db, ['192.168.1.0/24'], set())
    await db.commit()
    assert await db.get(DiscoveredHost, host.id) is host
    assert host.is_online is False


async def test_background_sync_runs_independently_of_network_scan_settings(db, monkeypatch):
    from unittest.mock import AsyncMock
    import app.scanner.scheduler as scheduler_module
    import app.services.proxmox as service

    db.add(ProxmoxIntegration(id=1, enabled=True))
    await db.commit()
    scheduler = scheduler_module.ScanScheduler()
    scheduler._running = True
    scheduler._is_setup_complete = AsyncMock(return_value=True)

    @asynccontextmanager
    async def test_session():
        yield db

    async def sync(session):
        assert session is db
        scheduler._running = False
        return {}

    sync_mock = AsyncMock(side_effect=sync)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(scheduler_module, 'async_session', test_session)
    monkeypatch.setattr(service, 'sync_proxmox', sync_mock)
    monkeypatch.setattr(scheduler_module.asyncio, 'sleep', sleep_mock)
    await scheduler._proxmox_loop()
    sync_mock.assert_awaited_once_with(db)
    sleep_mock.assert_awaited_once_with(scheduler_module.PROXMOX_SYNC_SECONDS)


async def test_dns_hostname_of_a_discovered_host_is_not_replaced(db):
    """The scanner writes the DNS name back on every scan; overwriting it would make the name flap."""
    connection = ProxmoxIntegration(id=1)
    dns = DiscoveredHost(ip='192.168.1.20', hostname='nas.lan')
    bare = DiscoveredHost(ip='192.168.1.21', hostname='192.168.1.21')
    device = Device(ip='192.168.1.20', hostname='nas.lan', display_name='nas')
    db.add_all([connection, dns, bare, device])
    await db.commit()
    result = await apply_guests(db, connection, [Guest('qemu/100', 'pve-nas', ['192.168.1.20']),
                                               Guest('lxc/101', 'pve-dns', ['192.168.1.21'])])
    assert dns.hostname == 'nas.lan' and device.hostname == 'nas.lan'
    assert device.display_name == 'pve-nas'  # 'nas' was only the short form of the hostname
    assert bare.hostname == 'pve-dns'
    assert result['updated_devices'] == 1
    # A guest renamed in Proxmox follows on the next sync, the DNS name still stays
    await apply_guests(db, connection, [Guest('lxc/101', 'pve-dns-2', ['192.168.1.21'])])
    assert bare.hostname == 'pve-dns-2'


def _connection():
    return ProxmoxIntegration(id=1, enabled=True, url='https://pve', token_id='reader@pve!inventory',
                              encrypted_secret=vault.encrypt('secret'))


async def test_result_is_dropped_when_the_settings_change_during_discovery(db, monkeypatch):
    connection = _connection()
    db.add_all([connection, Device(ip='192.168.1.10', display_name='192.168.1.10')])
    await db.commit()

    async def discover(self):
        # Another request points the integration at a different server meanwhile
        connection.url = 'https://other'
        await db.commit()
        return [Guest('qemu/100', 'nas', ['192.168.1.10'])], []
    monkeypatch.setattr(ProxmoxClient, 'discover', discover)
    with pytest.raises(ProxmoxError, match='changed during the sync'):
        await sync_proxmox(db)
    assert (await db.execute(select(Device))).scalar_one().display_name == '192.168.1.10'
    assert connection.inventory in ('{}', None) or json.loads(connection.inventory) == {}


async def test_saving_settings_does_not_wait_for_a_running_sync(client, db, admin_token, monkeypatch):
    db.add(_connection())
    await db.commit()
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_discover(self):
        started.set()
        await release.wait()
        return [], []
    monkeypatch.setattr(ProxmoxClient, 'discover', slow_discover)
    sync = asyncio.create_task(sync_proxmox(db))
    await started.wait()
    assert sync_lock.locked() and not proxmox_service.write_lock.locked()
    response = await asyncio.wait_for(client.put(
        '/api/settings/proxmox', headers={'Authorization': f'Bearer {admin_token}'},
        json={'enabled': False, 'url': 'https://pve', 'token_id': 'reader@pve!inventory'}), timeout=5)
    assert response.status_code == 200, response.text
    release.set()
    with pytest.raises(ProxmoxError, match='changed during the sync'):
        await sync


async def test_saving_and_removing_are_audited_without_the_secret(client, db, admin_token):
    from app.models.audit import AuditEvent
    headers = {'Authorization': f'Bearer {admin_token}'}
    await client.put('/api/settings/proxmox', headers=headers, json={
        'enabled': True, 'url': 'https://pve:8006', 'token_id': 'reader@pve!inventory', 'token_secret': 'top-secret'})
    await client.delete('/api/settings/proxmox', headers=headers)
    events = (await db.execute(select(AuditEvent).where(AuditEvent.action.like('proxmox.%')))).scalars().all()
    assert [e.action for e in events] == ['proxmox.save', 'proxmox.delete']
    assert all('top-secret' not in f'{e.target} {e.detail}' for e in events)


@pytest.fixture(autouse=True)
def _scan_subnets(monkeypatch):
    """Tests run with 192.168.1.0/24 as the scanned network, whatever this machine's own LAN is."""
    async def subnets(db):
        return ['192.168.1.0/24']
    monkeypatch.setattr(proxmox_service, '_scan_subnets', subnets)
    proxmox_service.clear_report()


async def test_only_addresses_in_the_scan_subnets_are_used(db):
    """Docker bridges and IPv6 inside guests are listed, not turned into discovered hosts or conflicts."""
    connection = ProxmoxIntegration(id=1)
    db.add_all([connection, Device(ip='10.9.9.9', display_name='10.9.9.9')])
    await db.commit()
    result = await apply_guests(db, connection, [
        Guest('qemu/100', 'docker-a', ['172.17.0.1', '192.168.1.10', 'fd00::10']),
        Guest('qemu/101', 'docker-b', ['172.17.0.1', '192.168.1.11', '10.9.9.9']),
    ], ['192.168.1.0/24'])
    assert result['conflicts'] == 0 and result['outside'] == 3
    assert set(json.loads(connection.inventory)) == {'192.168.1.10', '192.168.1.11', '10.9.9.9'}  # a known device counts
    ips = {h.ip for h in (await db.execute(select(DiscoveredHost))).scalars()}
    assert '172.17.0.1' not in ips and 'fd00::10' not in ips
    report = proxmox_service.last_report
    statuses = {a['ip']: a['status'] for g in report['guests'] for a in g['addresses']}
    assert statuses == {'172.17.0.1': 'outside', '192.168.1.10': 'new_host', 'fd00::10': 'outside',
                        '192.168.1.11': 'new_host', '10.9.9.9': 'renamed'}


async def test_conflicts_name_both_guests_in_the_report(db):
    connection = ProxmoxIntegration(id=1)
    db.add(connection)
    await db.commit()
    result = await apply_guests(db, connection, [Guest('qemu/100', 'alpha', ['192.168.1.10']),
                                               Guest('lxc/101', 'beta', ['192.168.1.10', '192.168.1.11'])],
                                ['192.168.1.0/24'])
    assert result['conflicts'] == 1
    assert proxmox_service.last_report['conflicts'] == [{'ip': '192.168.1.10', 'guests': ['alpha', 'beta']}]
    beta = next(g for g in proxmox_service.last_report['guests'] if g['name'] == 'beta')
    assert beta['addresses'] == [{'ip': '192.168.1.10', 'status': 'conflict'}, {'ip': '192.168.1.11', 'status': 'new_host'}]


async def test_report_is_cleared_when_the_connection_is_removed(client, db, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    proxmox_service.last_report = {'guests': []}
    assert (await client.get('/api/settings/proxmox/report', headers=headers)).json() == {'report': {'guests': []}}
    db.add(ProxmoxIntegration(id=1, url='https://pve', token_id='reader@pve!inventory'))
    await db.commit()
    assert (await client.delete('/api/settings/proxmox', headers=headers)).status_code == 204
    assert (await client.get('/api/settings/proxmox/report', headers=headers)).json() == {'report': None}


@pytest.fixture
def no_lookups(monkeypatch):
    """Adding a device looks up MAC, vendor and DNS; tests do not touch the network."""
    import app.api.devices as devices_api

    async def nothing(device, ip):
        return None
    monkeypatch.setattr(devices_api, '_fill_new_device_details', nothing)


async def test_add_to_dashboard_creates_named_devices_only_for_synced_addresses(client, db, admin_token, no_lookups):
    headers = {'Authorization': f'Bearer {admin_token}'}
    connection = ProxmoxIntegration(id=1, enabled=True, url='https://pve', token_id='reader@pve!inventory')
    db.add(connection)
    await db.commit()
    await apply_guests(db, connection, [Guest('qemu/100', 'nas', ['192.168.1.10']), Guest('lxc/101', 'dns', ['192.168.1.11'])],
                       ['192.168.1.0/24'])
    assert (await db.execute(select(Device))).scalars().all() == []  # a sync alone never adds devices

    response = await client.post('/api/settings/proxmox/add-to-dashboard', headers=headers, json={'ips': ['192.168.1.10']})
    assert response.status_code == 200, response.text
    assert [(a['ip'], a['name']) for a in response.json()['added']] == [('192.168.1.10', 'nas')]
    device = (await db.execute(select(Device))).scalar_one()
    assert device.display_name == 'nas'
    host = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == '192.168.1.10'))).scalar_one()
    assert host.is_monitored is True
    statuses = {a['ip']: a['status'] for g in proxmox_service.last_report['guests'] for a in g['addresses']}
    assert statuses == {'192.168.1.10': 'device', '192.168.1.11': 'new_host'}

    # Not from the last sync: refused, nothing created
    response = await client.post('/api/settings/proxmox/add-to-dashboard', headers=headers, json={'ips': ['192.168.1.99']})
    assert response.status_code == 400
    assert len((await db.execute(select(Device))).scalars().all()) == 1


async def test_add_to_dashboard_keeps_an_existing_device_and_its_name(client, db, admin_token, no_lookups):
    headers = {'Authorization': f'Bearer {admin_token}'}
    db.add_all([ProxmoxIntegration(id=1, enabled=True, inventory=json.dumps({'192.168.1.10': {'name': 'nas', 'guest': 'qemu/100'}})),
                Device(ip='192.168.1.10', display_name='My storage')])
    await db.commit()
    response = await client.post('/api/settings/proxmox/add-to-dashboard', headers=headers, json={'ips': ['192.168.1.10']})
    assert response.json()['added'][0]['name'] == 'My storage'
    assert len((await db.execute(select(Device))).scalars().all()) == 1
