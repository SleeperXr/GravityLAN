import asyncio
import hashlib
import hmac
import weakref
from typing import Callable, TypeVar

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Argon2id with argon2-cffi's defaults (t=3, m=64 MiB, p=4), the same parameters passlib used before:
# the parameters are stored in each hash, so hashes written by older versions keep verifying.
_hasher = PasswordHasher()

# One Argon2id run takes 64 MiB and tens to hundreds of milliseconds. It runs in a worker thread so
# the event loop keeps serving terminals, logs and agent reports; at most this many run at once,
# so parallel logins cannot add up to gigabytes.
MAX_PARALLEL_HASHES = 2
_T = TypeVar("_T")
_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


async def run_hashing(func: Callable[..., _T], *args) -> _T:
    """Run ``hash_password`` or ``verify_password`` (or a stand-in) off the event loop, a few at a time."""
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(MAX_PARALLEL_HASHES)
    async with gate:
        return await asyncio.to_thread(func, *args)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2 hash; anything else (also a bcrypt hash) does not match."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerificationError, InvalidHashError):
        return False


def looks_hashed(value: str) -> bool:
    """Whether a stored value is a password hash rather than a legacy plain-text value."""
    return value.startswith("$argon2") or value.startswith("$2b$") or value.startswith("$2a$")


def secure_compare(a: str, b: str) -> bool:
    """Constant-time comparison for tokens/secrets."""
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


# The master token is stored like agent and API tokens: only its SHA-256, tagged, so a copied
# database file (or volume backup) does not hand out a working admin credential.
MASTER_TOKEN_PREFIX = "sha256:"


def hash_master_token(token: str) -> str:
    """Storage form of the master token: ``sha256:<hex digest>``."""
    return MASTER_TOKEN_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def master_token_matches(presented: str | None, stored: str | None) -> bool:
    """Check a presented master token; a stored hash is never accepted as the token itself.

    An untagged stored value is a plaintext token from an older release; the startup
    migration replaces it with its hash, until then it is compared as it is.
    """
    if not presented or not stored:
        return False
    if stored.startswith(MASTER_TOKEN_PREFIX):
        return secure_compare(hash_master_token(presented), stored)
    return secure_compare(presented, stored)
