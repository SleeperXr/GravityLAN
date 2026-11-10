"""The in-memory browser session store (app/services/session_service.py) on its own."""

import pytest

from app.services import session_service
from app.services.session_service import SessionStore


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1_000_000.0}
    monkeypatch.setattr(session_service.time, "time", lambda: now["t"])
    return now


def test_a_session_is_found_and_touched(clock):
    store = SessionStore(session_lifetime_seconds=100)
    sid = store.create_session(user_agent="Firefox")
    clock["t"] += 10

    session = store.get_session(sid)
    assert (session.user_agent, session.last_seen, session.created_at) == ("Firefox", clock["t"], clock["t"] - 10)


@pytest.mark.parametrize("sid", [None, "", "token_abc", "session_unknown"])
def test_unknown_or_malformed_ids_find_nothing(clock, sid):
    assert SessionStore().get_session(sid) is None


def test_lifetime_counts_from_creation_not_last_use(clock):
    store = SessionStore(session_lifetime_seconds=100)
    sid = store.create_session()
    clock["t"] += 90
    assert store.get_session(sid) is not None
    clock["t"] += 20  # 110 s after creation, though last used 20 s ago
    assert store.get_session(sid) is None
    assert store.delete_session(sid) is False  # the expired one was dropped


def test_delete_all_except_keeps_one(clock):
    store = SessionStore()
    keep, a, b = (store.create_session() for _ in range(3))
    assert store.delete_all_except(keep) == 2
    assert [store.get_session(s) is not None for s in (keep, a, b)] == [True, False, False]
    assert store.delete_all_except(None) == 1


def test_has_browser_session_needs_a_live_session_cookie(clock, monkeypatch):
    store = SessionStore()
    monkeypatch.setattr(session_service, "session_store", store)
    live = store.create_session()
    conn = lambda cookie: type("Conn", (), {"cookies": {"gravitylan_token": cookie} if cookie else {}})()  # noqa: E731

    assert session_service.has_browser_session(conn(live)) is True
    assert session_service.has_browser_session(conn("session_gone")) is False
    assert session_service.has_browser_session(conn("api-token")) is False  # an API token is no browser session
    assert session_service.has_browser_session(conn(None)) is False


def test_prune_and_clear(clock):
    store = SessionStore(session_lifetime_seconds=100)
    old = store.create_session()
    clock["t"] += 60
    young = store.create_session()
    clock["t"] += 50

    store.prune_expired_sessions()
    assert store.get_session(old) is None and store.get_session(young) is not None

    store.clear()
    assert store.get_session(young) is None
