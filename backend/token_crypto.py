"""v4.0 Phase C — Symmetric encryption for stored OAuth tokens.

Meta long-lived user tokens live ~60 days; page tokens don't expire until the
user changes their password. We never want them in plaintext at rest, so
Fernet-encrypt on write, decrypt on read. Key lives in TOKEN_ENCRYPTION_KEY
(env), generated once and kept in Railway/Supabase secrets.

Rotation (the token vault, Phase 0 of the agentic ads plan):
    TOKEN_ENCRYPTION_KEY encrypts; it and any keys in TOKEN_ENCRYPTION_KEY_OLD
    (comma-separated) decrypt — a MultiFernet, which tries each in turn. To
    rotate: put a new key in TOKEN_ENCRYPTION_KEY and the old one in
    TOKEN_ENCRYPTION_KEY_OLD, deploy, run scripts/rotate_tokens.py to
    re-encrypt every stored token under the new key, then drop the old key.
    Reads keep working throughout.
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from config import settings

log = logging.getLogger("token_crypto")


class TokenCryptoError(RuntimeError):
    pass


def _one(key: str, name: str) -> Fernet:
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise TokenCryptoError(f"invalid {name}: {e}") from e


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    """The current key first (it encrypts), then the old ones (they only decrypt)."""
    key = (settings.token_encryption_key or "").strip()
    if not key:
        raise TokenCryptoError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' "
            "and add it to the API + worker + beat services."
        )
    # Fernet needs a url-safe 32-byte base64-encoded key
    old = [k.strip() for k in (settings.token_encryption_key_old or "").split(",") if k.strip()]
    return MultiFernet([_one(key, "TOKEN_ENCRYPTION_KEY"), *(_one(k, "TOKEN_ENCRYPTION_KEY_OLD") for k in old)])


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
        raise TokenCryptoError("token decryption failed — no configured key (TOKEN_ENCRYPTION_KEY or TOKEN_ENCRYPTION_KEY_OLD) wrote it")


def rotate(ciphertext: bytes | memoryview | None) -> bytes | None:
    """The same token, re-encrypted under the current key (scripts/rotate_tokens.py)."""
    if ciphertext is None:
        return None
    b = bytes(ciphertext) if isinstance(ciphertext, memoryview) else ciphertext
    try:
        return _fernet().rotate(b)
    except InvalidToken:
        raise TokenCryptoError("token rotation failed — no configured key wrote it")
