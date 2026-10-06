from __future__ import annotations

import hashlib
import hmac
import secrets
from argon2 import PasswordHasher, exceptions as argon_exceptions

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return PASSWORDS.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, password)
    except (argon_exceptions.VerificationError, argon_exceptions.InvalidHashError):
        return False


def opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_digest(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).hexdigest()


def hash_otp(email: str, purpose: str, otp: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), f"{email.lower()}:{purpose}:{otp}".encode(), hashlib.sha256).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
