"""Argon2id password hashing (ADR-010 §6)."""

import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

# t=3, m=64 MiB, p=1: above the OWASP minimum (t=2, m=19 MiB, p=1); ~107 ms on the dev machine.
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)

# Verified against for unknown emails so every failed login does the same work.
_DUMMY_HASH = HASHER.hash("hermecious-timing-equalizer-not-a-credential")


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, email: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters")
    if password.strip().lower() == email.strip().lower():
        raise PasswordPolicyError("password must not equal the email address")


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work check. `None` (unknown user) still runs a full verification."""
    try:
        return HASHER.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return HASHER.check_needs_rehash(password_hash)


def canonical_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email).strip().lower()
