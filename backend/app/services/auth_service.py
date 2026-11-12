from passlib.context import CryptContext
import hashlib
import hmac

# Password hashing configuration
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using Argon2 (fallback to bcrypt)."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)

def looks_hashed(value: str) -> bool:
    """Check if a value looks like a hashed password."""
    # passlib hashes usually start with $
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
