"""A page on another origin cannot send state-changing requests with the browser's session cookie.

SameSite=Lax does not separate ports or subdomains of one host, so the HTTP side needs the same
Origin check the WebSockets have. The password hashing runs off the event loop.
"""

import asyncio
import threading

import pytest

from app.services import auth_service
from app.services.session_service import session_store

MASTER = {"Authorization": "Bearer test-admin-token-12345"}
HOST = "gravity.test"


def _login(client):
    client.cookies.set("gravitylan_token", session_store.create_session(user_agent=None))


# --- cookie + Origin ----------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"origin": "http://gravity.test:9000"},  # another port of the same host: same site, other origin
    {"origin": "https://evil.example"},
    {"origin": "null"},
    {"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
    {"origin": "http://gravity.test:9000", "sec-fetch-site": "same-site"},
])
async def test_a_cookie_write_from_another_origin_is_refused(client, admin_token, headers):
    _login(client)
    cookie = client.cookies.get("gravitylan_token")

    response = await client.post("/api/auth/logout", headers={"host": HOST, **headers})

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed"}
    assert session_store.get_session(cookie) is not None  # the refused logout did nothing


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {},  # scripts and old clients send no Origin
    {"origin": f"http://{HOST}"},
    {"origin": "http://gravity.test:9000", "sec-fetch-site": "same-origin"},  # a proxy that rewrites Host
])
async def test_a_cookie_write_from_the_same_origin_goes_through(client, admin_token, headers):
    _login(client)
    cookie = client.cookies.get("gravitylan_token")

    response = await client.post("/api/auth/logout", headers={"host": HOST, **headers})

    assert response.status_code == 200
    assert session_store.get_session(cookie) is None


@pytest.mark.asyncio
async def test_configured_cors_origins_may_write(client, admin_token, monkeypatch):
    from app.api import auth

    monkeypatch.setattr(auth.settings, "cors_origins", ["http://localhost:5173"])
    _login(client)

    response = await client.post("/api/auth/logout", headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reads_and_calls_without_a_cookie_are_not_checked(client, admin_token):
    cross = {"host": HOST, "origin": "https://evil.example"}
    _login(client)

    assert (await client.get("/api/health", headers=cross)).status_code != 403  # a read
    client.cookies.clear()  # no cookie: nothing for another site to ride on
    response = await client.post("/api/auth/logout", headers={**cross, **MASTER})
    assert response.status_code == 200


# --- sessions -----------------------------------------------------------------

def test_a_full_store_makes_room_by_dropping_the_longest_unused_session(monkeypatch):
    from app.services import session_service
    from app.services.session_service import SessionStore

    now = {"t": 1_000.0}
    monkeypatch.setattr(session_service.time, "time", lambda: now["t"])
    store = SessionStore(max_sessions=3)
    first, second, third = (store.create_session() for _ in range(3))
    now["t"] += 5
    store.get_session(first)  # used again: the second one is now the stalest
    now["t"] += 5

    fourth = store.create_session()

    assert [store.get_session(s) is not None for s in (first, second, third, fourth)] == [True, False, True, True]
    assert len(store._sessions) == 3


def test_creating_a_session_drops_expired_ones(monkeypatch):
    from app.services import session_service
    from app.services.session_service import SessionStore

    now = {"t": 1_000.0}
    monkeypatch.setattr(session_service.time, "time", lambda: now["t"])
    store = SessionStore(session_lifetime_seconds=100)
    store.create_session()
    now["t"] += 200

    store.create_session()

    assert len(store._sessions) == 1


# --- hashing ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hashing_runs_in_a_worker_thread_and_at_most_a_few_at_a_time():
    loop_thread = threading.get_ident()
    running, peak, threads = 0, 0, set()
    lock = threading.Lock()

    def slow(value):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            threads.add(threading.get_ident())
        threading.Event().wait(0.05)
        with lock:
            running -= 1
        return value

    results = await asyncio.gather(*(auth_service.run_hashing(slow, i) for i in range(6)))

    assert results == list(range(6))
    assert loop_thread not in threads
    assert peak <= auth_service.MAX_PARALLEL_HASHES
