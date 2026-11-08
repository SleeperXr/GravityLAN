"""app/services/ssh_terminal.py once the shell runs: how each side ending ends the bridge.
Everything is faked; nothing connects anywhere."""

import asyncio
import json
import logging
import queue

import pytest
from fastapi import WebSocketDisconnect

import app.services.ssh_terminal as st
from app.services.ssh_terminal import ConnectionTarget, HostKeyInfo, TerminalError

TARGET = ConnectionTarget(host="192.0.2.10", port=22, username="admin", label="nas", password="pw")
DISCONNECT = {"type": "websocket.disconnect"}


def text(payload) -> dict:
    return {"type": "websocket.receive", "text": payload if isinstance(payload, str) else json.dumps(payload)}


class Session:
    """A shell whose output the test scripts; recv raises what it is given."""

    def __init__(self, target=None, output=(), auth_error=None):
        self.queue = queue.Queue()
        for item in output:
            self.queue.put(item)
        self.auth_error = auth_error
        self.sent, self.resized, self.closed = [], [], False

    def connect(self):
        return HostKeyInfo("ssh-ed25519", "SHA256:abc", "ssh-ed25519 AAAA")

    def authenticate(self):
        if self.auth_error:
            raise TerminalError(self.auth_error)

    def open_shell(self, cols, rows):
        pass

    def recv(self):
        item = self.queue.get(timeout=5)
        if isinstance(item, Exception):
            raise item
        return item

    def send(self, data):
        self.sent.append(data)

    def resize(self, cols, rows):
        self.resized.append((cols, rows))

    def close(self):
        self.closed = True
        self.queue.put(b"")


class Socket:
    """Hands out scripted frames, then stays silent; an exception in the script is raised."""

    def __init__(self, incoming=(), send_fails=False, close_fails=False):
        self.incoming = list(incoming)
        self.send_fails, self.close_fails = send_fails, close_fails
        self.binary, self.control, self.closed = [], [], False

    async def receive(self):
        if not self.incoming:
            await asyncio.sleep(3600)
        frame = self.incoming.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    async def send_bytes(self, data):
        if self.send_fails:
            raise RuntimeError("client gone")
        self.binary.append(data)

    async def send_text(self, data):
        self.control.append(json.loads(data))

    async def close(self, code=1000):
        if self.close_fails:
            raise RuntimeError("already closed")
        self.closed = True


class KnownHosts:
    async def check(self, host, port, info):
        return "known", info.fingerprint

    async def remember(self, host, port, info):
        raise AssertionError("a known key is not stored again")


async def pump(ws: Socket, session: Session) -> str:
    try:
        return await st._pump(ws, session)
    finally:
        session.queue.put(b"")  # lets the reader thread finish


@pytest.fixture(autouse=True)
def no_idle_limit(monkeypatch):
    monkeypatch.setattr(st.settings, "ssh_idle_timeout_minutes", 0)
    monkeypatch.setattr(st, "_active_sessions", set())


async def test_shell_output_reaches_the_browser_until_the_shell_ends():
    ws = Socket()
    assert await pump(ws, Session(output=[b"hello", b"world", b""])) == "remote"
    assert ws.binary == [b"hello", b"world"]


async def test_a_broken_shell_connection_counts_as_the_shell_ending():
    assert await pump(Socket(), Session(output=[OSError("reset")])) == "remote"


async def test_a_browser_that_stops_accepting_output_ends_the_bridge():
    assert await pump(Socket(send_fails=True), Session(output=[b"hello"])) == "client"


async def test_keystrokes_reach_the_shell():
    session = Session()
    ws = Socket([{"type": "websocket.receive", "bytes": b"ls\n"}, DISCONNECT])
    assert await pump(ws, session) == "client"
    assert session.sent == [b"ls\n"]


async def test_a_resize_is_applied_within_limits():
    session = Session()
    assert await pump(Socket([text({"type": "resize", "cols": 9999, "rows": 1}), DISCONNECT]), session) == "client"
    assert session.resized == [(st.MAX_COLS, st.MIN_SIZE)]


async def test_a_resize_without_a_size_falls_back_to_the_default():
    session = Session()
    assert await pump(Socket([text({"type": "resize"}), DISCONNECT]), session) == "client"
    assert session.resized == [(80, 24)]


@pytest.mark.parametrize("frame", ["not json", {"type": "hostkey_accept"}])
async def test_other_text_frames_are_ignored_while_the_shell_runs(frame):
    session = Session()
    assert await pump(Socket([text(frame), DISCONNECT]), session) == "client"
    assert (session.sent, session.resized) == ([], [])


async def test_empty_frames_do_nothing():
    session = Session()
    assert await pump(Socket([{"type": "websocket.receive"}, DISCONNECT]), session) == "client"
    assert (session.sent, session.resized) == ([], [])


async def test_a_silent_browser_is_timed_out(monkeypatch):
    monkeypatch.setattr(st.settings, "ssh_idle_timeout_minutes", 0.0005)
    assert await pump(Socket(), Session()) == "idle"


async def test_a_disconnect_raised_by_the_socket_counts_as_the_client_leaving():
    assert await pump(Socket([WebSocketDisconnect(1006)]), Session()) == "client"


async def test_an_unexpected_input_error_is_not_hidden():
    with pytest.raises(RuntimeError, match="boom"):
        await pump(Socket([RuntimeError("boom")]), Session())


async def run(ws: Socket, session: Session) -> None:
    await st.run_terminal(ws, TARGET, session_factory=lambda target: session, known_hosts=KnownHosts())


async def test_the_browser_is_told_when_the_shell_ends():
    ws = Socket()
    session = Session(output=[b""])
    await run(ws, session)
    assert [m.get("stage") for m in ws.control[:3]] == ["connecting", "authenticating", "connected"]
    assert ws.control[-1] == {"type": "closed", "reason": "remote"}
    assert session.closed and ws.closed
    assert st.active_session_count() == 0


async def test_the_browser_is_told_about_an_idle_timeout(monkeypatch):
    monkeypatch.setattr(st.settings, "ssh_idle_timeout_minutes", 0.0005)
    ws = Socket()
    await run(ws, Session())
    assert ws.control[-1] == {"type": "closed", "reason": "idle"}


async def test_nothing_is_announced_to_a_browser_that_left():
    ws = Socket([DISCONNECT])
    await run(ws, Session())
    assert not [m for m in ws.control if m["type"] == "closed"]
    assert ws.closed


async def test_a_login_error_is_shown_and_no_shell_starts(caplog):
    ws = Socket()
    session = Session(auth_error="Authentication failed for user 'admin'.")
    with caplog.at_level(logging.INFO, logger=st.logger.name):
        await run(ws, session)
    assert ws.control[-1] == {"type": "error", "message": "Authentication failed for user 'admin'."}
    assert "connected" not in [m.get("stage") for m in ws.control]
    assert session.closed
    assert "SSH terminal closed" not in caplog.text


async def test_a_socket_that_cannot_be_closed_does_not_matter():
    session = Session(output=[b""])
    await run(Socket(close_fails=True), session)
    assert session.closed
    assert st.active_session_count() == 0


@pytest.mark.parametrize(
    "ws, output, expected",
    [(Socket(), [b""], None), (Socket([RuntimeError("boom")]), [], "error")],
    ids=["clean end", "crash in the bridge"],
)
async def test_an_opened_session_is_always_logged_as_closed(caplog, ws, output, expected):
    with caplog.at_level(logging.INFO, logger=st.logger.name):
        await run(ws, Session(output=output))
    assert "SSH terminal opened" in caplog.text
    assert "SSH terminal closed: admin@192.0.2.10:22" in caplog.text
    if expected:
        assert ws.control[-1]["type"] == expected
