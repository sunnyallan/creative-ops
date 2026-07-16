"""v4.0 Phase C — Symmetric encryption for stored OAuth tokens.

Meta long-lived user tokens live ~60 days; page tokens don't expire until the
user changes their password. We never want them in plaintext at rest, so
Fernet-encrypt on write, decrypt on read. Key lives in TOKEN_ENCRYPTION_KEY
(env), generated once and kept in Railway/Supabase secrets.

Rotation strategy (documented, deferred):
    Store per-token version tag; on Fernet.InvalidToken, retry with a
    known-old key from TOKEN_ENCRYPTION_KEY_OLD. Not implemented yet — we
    have no tokens in prod to rotate.
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from config import settings

log = logging.getLogger("token_crypto")


class TokenCryptoError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = (settings.token_encryption_key or "").strip()
    if not key:
        raise TokenCryptoError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' "
            "and add it to the API + worker + beat services."
        )
    # Fernet needs a url-safe 32-byte base64-encoded key
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise TokenCryptoError(f"invalid TOKEN_ENCRYPTION_KEY: {e}") from e


def encrypt(plaintext: str | None) -> bytes | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes | memoryview | None) -> str | None:
    if ciphertext is None:
        return None
    b = bytes(ciphertext) if isinstance(ciphertext, memoryview) else ciphertext
    try:
        return _fernet().decrypt(b).decode("utf-8")
    except InvalidToken:
        raise TokenCryptoError("token decryption failed — TOKEN_ENCRYPTION_KEY may have rotated")
