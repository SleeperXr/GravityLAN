"""app/services/ssh_terminal.py below the WebSocket: the paramiko session (handshake, login errors,
shell), the TCP fallback to the bridge gateway, the known-host store and the host key prompt.
paramiko is replaced by small fakes; nothing connects anywhere."""

import asyncio
import json
from contextlib import asynccontextmanager

import paramiko
import pytest
from sqlalchemy import select

import app.services.ssh_terminal as st
from app.models.ssh import SshKnownHost
from app.services.ssh_terminal import ConnectionTarget, HostKeyInfo, TerminalError, TerminalSession
from app.services.ssh_utils import SSHKeyPassphraseRequired

INFO = HostKeyInfo("ssh-ed25519", "SHA256:abc", "ssh-ed25519 AAAA")


def target(**kw) -> ConnectionTarget:
    base = dict(host="192.0.2.10", port=22, username="admin", label="nas", password="pw")
    base.update(kw)
    return ConnectionTarget(**base)


class FakeKey:
    def get_name(self):
        return "ssh-ed25519"

    fingerprint = "SHA256:abc"

    def get_base64(self):
        return "AAAA"


class FakeChannel:
    def __init__(self):
        self.sent, self.sizes, self.closed = [], [], False

    def get_pty(self, term, width, height):
        self.sizes.append((term, width, height))

    def invoke_shell(self):
        pass

    def recv(self, n):
        return b"out"

    def sendall(self, data):
        self.sent.append(data)

    def resize_pty(self, width, height):
        self.sizes.append(("resize", width, height))

    def close(self):
        self.closed = True


class FakeTransport:
    """Records calls; ``fail`` maps a method name to the exception it raises."""

    def __init__(self, sock=None, fail=None, authenticated=True):
        self.fail = fail or {}
        self.authenticated = authenticated
        self.calls, self.closed, self.channel = [], False, FakeChannel()

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def start_client(self, timeout):
        self._maybe_fail("start_client")

    def get_remote_server_key(self):
        return FakeKey()

    def auth_publickey(self, user, key):
        self.calls.append(("publickey", user, key))
        self._maybe_fail("auth")

    def auth_password(self, user, password, fallback):
        self.calls.append(("password", user, password, fallback))
        self._maybe_fail("auth")

    def is_authenticated(self):
        return self.authenticated

    def set_keepalive(self, seconds):
        self.calls.append(("keepalive", seconds))

    def open_session(self, timeout):
        self._maybe_fail("open_session")
        return self.channel

    def close(self):
        self.closed = True


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(st, "_open_socket", lambda host, port: object())


def connected(monkeypatch, **transport_kw) -> tuple[TerminalSession, FakeTransport]:
    fake = FakeTransport(**transport_kw)
    monkeypatch.setattr(st.paramiko, "Transport", lambda sock: fake)
    session = TerminalSession(target())
    return session, fake


# --- sizes and sockets -------------------------------------------------------------------------

@pytest.mark.parametrize("cols, rows, expected", [(80, 24, (80, 24)), (1, 1, (2, 2)), (9999, 9999, (500, 200)), ("120", "40", (120, 40))])
def test_clamp_size(cols, rows, expected):
    assert st.clamp_size(cols, rows) == expected


def test_open_socket_retries_the_bridge_gateway_for_the_docker_host(monkeypatch):
    tried = []

    def connect(addr, timeout):
        tried.append(addr)
        if addr[0] == "192.0.2.10":
            raise OSError(113, "No route to host")
        return "socket"

    monkeypatch.setattr(st.socket, "create_connection", connect)
    monkeypatch.setattr("app.services.ssh_utils.host_bypass_gateway", lambda host: "172.17.0.1")
    assert st._open_socket("192.0.2.10", 22) == "socket"
    assert tried == [("192.0.2.10", 22), ("172.17.0.1", 22)]


def test_open_socket_reports_the_first_error_when_the_gateway_fails_too(monkeypatch):
    def refuse(addr, timeout):
        raise OSError(111, "Connection refused")

    monkeypatch.setattr(st.socket, "create_connection", refuse)
    monkeypatch.setattr("app.services.ssh_utils.host_bypass_gateway", lambda host: "172.17.0.1")
    with pytest.raises(TerminalError, match=r"Cannot reach 192\.0\.2\.10:22 \(Connection refused\)"):
        st._open_socket("192.0.2.10", 22)


def test_open_socket_without_a_gateway(monkeypatch):
    def down(addr, timeout):
        raise OSError("down")

    monkeypatch.setattr(st.socket, "create_connection", down)
    monkeypatch.setattr("app.services.ssh_utils.host_bypass_gateway", lambda host: None)
    with pytest.raises(TerminalError, match="Cannot reach"):
        st._open_socket("192.0.2.10", 22)


# --- TerminalSession ---------------------------------------------------------------------------

def test_connect_returns_the_host_key(monkeypatch, no_network):
    session, _ = connected(monkeypatch)
    assert session.connect() == HostKeyInfo("ssh-ed25519", "SHA256:abc", "ssh-ed25519 AAAA")


@pytest.mark.parametrize("error", [paramiko.SSHException("bad banner"), EOFError(), OSError("reset")])
def test_a_failed_handshake_closes_the_transport(monkeypatch, no_network, error):
    session, fake = connected(monkeypatch, fail={"start_client": error})
    with pytest.raises(TerminalError, match="SSH handshake failed"):
        session.connect()
    assert fake.closed


def test_password_login_with_keyboard_interactive_fallback(monkeypatch, no_network):
    session, fake = connected(monkeypatch)
    session.connect()
    session.authenticate()
    assert fake.calls == [("password", "admin", "pw", True), ("keepalive", 30)]


def test_key_login_loads_the_key_with_its_passphrase(monkeypatch, no_network):
    session, fake = connected(monkeypatch)
    session.target = target(private_key="PEM", passphrase="secret", password=None)
    monkeypatch.setattr(st, "load_private_key", lambda pem, passphrase: ("key", pem, passphrase))
    session.connect()
    session.authenticate()
    assert fake.calls[0] == ("publickey", "admin", ("key", "PEM", "secret"))


@pytest.mark.parametrize("raised, message", [
    (paramiko.BadAuthenticationType("no", ["publickey"]), r"allowed: publickey"),
    (paramiko.AuthenticationException("nope"), r"Authentication failed for user 'admin'"),
    (paramiko.SSHException("broken"), r"SSH error during login: broken"),
])
def test_login_errors_become_readable_messages(monkeypatch, no_network, raised, message):
    session, _ = connected(monkeypatch, fail={"auth": raised})
    session.connect()
    with pytest.raises(TerminalError, match=message):
        session.authenticate()


@pytest.mark.parametrize("raised, message", [
    (SSHKeyPassphraseRequired("x"), "needs a passphrase"),
    (ValueError("not a key"), "could not be loaded: not a key"),
])
def test_key_problems_become_readable_messages(monkeypatch, no_network, raised, message):
    session, _ = connected(monkeypatch)
    session.target = target(private_key="PEM", password=None)

    def broken(pem, passphrase):
        raise raised

    monkeypatch.setattr(st, "load_private_key", broken)
    session.connect()
    with pytest.raises(TerminalError, match=message):
        session.authenticate()


def test_login_needs_a_key_or_password(monkeypatch, no_network):
    session, _ = connected(monkeypatch)
    session.target = target(password=None)
    session.connect()
    with pytest.raises(TerminalError, match="No key or password"):
        session.authenticate()


def test_partial_authentication_is_refused(monkeypatch, no_network):
    session, _ = connected(monkeypatch, authenticated=False)
    session.connect()
    with pytest.raises(TerminalError, match="2FA"):
        session.authenticate()


def test_shell_io_and_close(monkeypatch, no_network):
    session, fake = connected(monkeypatch)
    session.connect()
    session.open_shell(100, 30)
    assert session.recv() == b"out"
    session.send(b"ls\n")
    session.resize(120, 40)
    session.close()
    assert fake.channel.sizes == [("xterm-256color", 100, 30), ("resize", 120, 40)]
    assert fake.channel.sent == [b"ls\n"]
    assert fake.channel.closed and fake.closed


def test_shell_start_failure(monkeypatch, no_network):
    session, _ = connected(monkeypatch, fail={"open_session": paramiko.SSHException("no channel")})
    session.connect()
    with pytest.raises(TerminalError, match="Could not start a shell: no channel"):
        session.open_shell(80, 24)


def test_using_a_session_before_connecting():
    session = TerminalSession(target())
    with pytest.raises(TerminalError, match="Not connected"):
        session.authenticate()
    with pytest.raises(TerminalError, match="Shell not open"):
        session.recv()
    session.close()  # nothing open, nothing to fail


def test_close_survives_a_failing_channel(monkeypatch, no_network):
    session, fake = connected(monkeypatch)
    session.connect()
    session.open_shell(80, 24)

    def gone():
        raise OSError("gone")

    fake.channel.close = gone
    session.close()
    assert fake.closed


class _Closable:
    def __init__(self, error=None):
        self.error, self.closed = error, False

    def close(self):
        if self.error:
            raise self.error
        self.closed = True


def test_close_all_sessions_reports_and_survives_errors(monkeypatch):
    good, bad = _Closable(), _Closable(RuntimeError("stuck"))
    monkeypatch.setattr(st, "_active_sessions", {good, bad})
    assert st.close_all_sessions() == 2
    assert good.closed


# --- known hosts -------------------------------------------------------------------------------

@pytest.fixture
def store(db, monkeypatch):
    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr("app.database.async_session", session)
    return st.DbKnownHostStore()


async def test_known_host_store_trust_on_first_use(store):
    assert await store.check("192.0.2.10", 22, INFO) == ("unknown", None)

    await store.remember("192.0.2.10", 22, INFO)
    assert await store.check("192.0.2.10", 22, INFO) == ("known", "SHA256:abc")

    other = HostKeyInfo("ssh-rsa", "SHA256:new", "ssh-rsa BBBB")
    assert await store.check("192.0.2.10", 22, other) == ("changed", "SHA256:abc")
    # Another port of the same host is a different entry
    assert await store.check("192.0.2.10", 2222, INFO) == ("unknown", None)


async def test_remembering_again_replaces_the_key(store, db):
    await store.remember("192.0.2.10", 22, INFO)
    await store.remember("192.0.2.10", 22, HostKeyInfo("ssh-rsa", "SHA256:new", "ssh-rsa BBBB"))
    rows = (await db.execute(select(SshKnownHost))).scalars().all()
    assert [(r.key_type, r.fingerprint, r.public_key) for r in rows] == [("ssh-rsa", "SHA256:new", "ssh-rsa BBBB")]


# --- host key prompt ---------------------------------------------------------------------------

class FakeSocket:
    def __init__(self, incoming=()):
        self.incoming = list(incoming)
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def receive(self):
        if not self.incoming:
            await asyncio.sleep(3600)
        return self.incoming.pop(0)


class FixedStore:
    def __init__(self, status, fingerprint=None):
        self.answer = (status, fingerprint)
        self.remembered = []

    async def check(self, host, port, info):
        return self.answer

    async def remember(self, host, port, info):
        self.remembered.append((host, port, info))


async def test_known_key_needs_no_prompt():
    ws = FakeSocket()
    assert await st._verify_host_key(ws, FixedStore("known", "SHA256:abc"), target(), INFO, {}) is True
    assert ws.sent == []


async def test_changed_key_blocks_the_connection():
    ws = FakeSocket()
    assert await st._verify_host_key(ws, FixedStore("changed", "SHA256:old"), target(), INFO, {}) is False
    assert ws.sent[0]["known_fingerprint"] == "SHA256:old"
    assert ws.sent[1]["type"] == "error" and "changed" in ws.sent[1]["message"]


async def test_unknown_key_accepted_after_resizes_and_noise():
    ws = FakeSocket([
        {"type": "websocket.receive", "bytes": b"typed"},
        {"type": "websocket.receive", "text": "not json"},
        {"type": "websocket.receive", "text": json.dumps({"type": "resize", "cols": 132, "rows": 43})},
        {"type": "websocket.receive", "text": json.dumps({"type": "hostkey_accept"})},
    ])
    store, size = FixedStore("unknown"), {"cols": 80, "rows": 24}
    assert await st._verify_host_key(ws, store, target(), INFO, size) is True
    assert size == {"cols": 132, "rows": 43}
    assert store.remembered == [("192.0.2.10", 22, INFO)]


async def test_unknown_key_rejected():
    ws = FakeSocket([{"type": "websocket.receive", "text": json.dumps({"type": "hostkey_reject"})}])
    store = FixedStore("unknown")
    assert await st._verify_host_key(ws, store, target(), INFO, {}) is False
    assert ws.sent[-1] == {"type": "closed", "reason": "hostkey_rejected"}
    assert store.remembered == []


async def test_unanswered_prompt_times_out(monkeypatch):
    monkeypatch.setattr(st, "HOSTKEY_PROMPT_TIMEOUT", 0.01)
    ws = FakeSocket()
    assert await st._verify_host_key(ws, FixedStore("unknown"), target(), INFO, {}) is False
    assert ws.sent[-1]["message"] == "No answer to the host key prompt."


async def test_disconnect_during_the_prompt_propagates():
    ws = FakeSocket([{"type": "websocket.disconnect", "code": 1001}])
    with pytest.raises(st.WebSocketDisconnect):
        await st._verify_host_key(ws, FixedStore("unknown"), target(), INFO, {})


async def test_send_control_ignores_a_closed_socket():
    class Closed:
        async def send_text(self, text):
            raise RuntimeError("closed")

    await st._send_control(Closed(), {"type": "status"})


# --- run_terminal limits and unexpected errors ---------------------------------------------

class ClosingSocket(FakeSocket):
    def __init__(self):
        super().__init__()
        self.closed_with = []

    async def close(self, code=1000):
        self.closed_with.append(code)


async def test_too_many_sessions_are_refused(monkeypatch):
    monkeypatch.setattr(st, "_active_sessions", {object()})
    monkeypatch.setattr(st.settings, "ssh_max_sessions", 1)
    ws = ClosingSocket()
    await st.run_terminal(ws, target())
    assert "Too many open SSH sessions (max 1)" in ws.sent[0]["message"]
    assert ws.closed_with == [1013]


async def test_an_unexpected_error_is_reported_without_details(monkeypatch):
    class Exploding:
        def __init__(self, t):
            pass

        def connect(self):
            raise RuntimeError("secret internals")

        def close(self):
            pass

    monkeypatch.setattr(st, "_active_sessions", set())
    ws = ClosingSocket()
    await st.run_terminal(ws, target(), session_factory=Exploding, known_hosts=FixedStore("known"))
    assert ws.sent[-1] == {"type": "error", "message": "Unexpected server error, see the GravityLAN log."}
    assert st._active_sessions == set()
