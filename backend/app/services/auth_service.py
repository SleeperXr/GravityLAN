from passlib.context import CryptContext
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
