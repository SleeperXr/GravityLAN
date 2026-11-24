"""In-memory Session Store for GravityLAN.

WARNING: This is an In-Memory Session Store designed strictly as a temporary,
minimal-invasive solution for single-worker / single-process Homelab environments.
It is NOT designed to scale across multiple workers or load-balanced containers.
Active sessions will be lost when the application restarts.

Concurrency Note: Since Python's asyncio event loop is single-threaded, and all
operations in this store are synchronous CPU-bound dictionary operations with no 'await'
statements, context switches cannot occur during store access. Therefore, no locks
(threading or asyncio) are required for safety.
"""

import time
import secrets
from typing import Dict

class Session:
    def __init__(self, session_id: str, created_at: float, user_agent: str | None = None):
        self.session_id = session_id
        self.created_at = created_at
        self.last_seen = created_at
        self.user_agent = user_agent

MAX_SESSIONS = 128


class SessionStore:
    def __init__(
        self,
        session_lifetime_seconds: float = 60 * 60 * 24 * 7,  # Default 7 days
        max_sessions: int = MAX_SESSIONS,
    ):
        self._sessions: Dict[str, Session] = {}
        self.session_lifetime = session_lifetime_seconds
        self.max_sessions = max_sessions

    def create_session(self, user_agent: str | None = None) -> str:
        """Create a new session, store it, and return the session ID.

        Expired sessions are dropped first, and when the store is still full the session
        that was used longest ago makes room: a script that logs in over and over and
        throws its cookie away cannot grow the store without bound.
        """
        self.prune_expired_sessions()
        while len(self._sessions) >= self.max_sessions:
            stalest = min(self._sessions.values(), key=lambda s: s.last_seen)
            self.delete_session(stalest.session_id)
        session_id = f"session_{secrets.token_hex(32)}"
        now = time.time()
        self._sessions[session_id] = Session(
            session_id=session_id,
            created_at=now,
            user_agent=user_agent
        )
        return session_id

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve a session and update its last_seen timestamp if valid."""
        if not session_id or not session_id.startswith("session_"):
            return None
            
        session = self._sessions.get(session_id)
        if not session:
            return None

        now = time.time()
        # Check absolute expiration (created_at + lifetime)
        if now - session.created_at > self.session_lifetime:
            self.delete_session(session_id)
            return None

        # Update last seen
        session.last_seen = now
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID. Returns True if found and deleted."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def delete_all_except(self, keep_session_id: str | None) -> int:
        """Log out every session but `keep_session_id` (e.g. after a password change). Returns the count."""
        others = [sid for sid in self._sessions if sid != keep_session_id]
        for sid in others:
            self.delete_session(sid)
        return len(others)

    def prune_expired_sessions(self) -> None:
        """Remove all sessions that exceed the lifetime."""
        now = time.time()
        expired_ids = [
            sid for sid, sess in self._sessions.items()
            if now - sess.created_at > self.session_lifetime
        ]
        for sid in expired_ids:
            self.delete_session(sid)

    def clear(self) -> None:
        """Remove all active browser sessions (e.g. after a database factory reset)."""
        self._sessions.clear()


# Global single-process store instance
session_store = SessionStore()


def has_browser_session(conn) -> bool:
    """True when a request or WebSocket carries a live browser session cookie (not an API or master token)."""
    cookie = conn.cookies.get("gravitylan_token")
    return bool(cookie and cookie.startswith("session_") and session_store.get_session(cookie))
