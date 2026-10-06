from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FileEncryptor:
    """AES-256-GCM envelope: 12-byte random nonce followed by authenticated ciphertext."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("AES-256-GCM requires a 32-byte key")
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: bytes, *, associated_data: bytes = b"") -> bytes:
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(nonce, plaintext, associated_data)

    def decrypt(self, envelope: bytes, *, associated_data: bytes = b"") -> bytes:
        if len(envelope) < 29:
            raise ValueError("Encrypted file is truncated")
        return self._cipher.decrypt(envelope[:12], envelope[12:], associated_data)
