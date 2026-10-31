"""Worker API keys: ocrk_<40 hex>, SHA-256 at rest, constant-time verify.

The plaintext leaves create_key once and is never written down: the database
holds only the hash, so a stolen ocr.db cannot be replayed as a key. verify()
hashes the candidate and compares hashes with hmac.compare_digest, and a
revoked key stops resolving on the next call.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3

from app import config
from app.db import _now

# ASSUMPTION: revocation targets the key id an operator reads from the keys
# table; there is no revoke-by-worker or revoke-by-plaintext-key path.


def generate_key() -> str:
    """Fresh plaintext key, ocrk_ + 40 hex (config.KEY_BYTES random bytes)."""
    return config.KEY_PREFIX + secrets.token_hex(config.KEY_BYTES)


def hash_key(key: str) -> str:
    """Hex SHA-256 of the plaintext; the only key form the database sees."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_key(conn: sqlite3.Connection, worker: str) -> tuple[int, str]:
    """Register a key for a worker; returns (key_id, plaintext) — show it once."""
    plaintext = generate_key()
    cur = conn.execute(
        "INSERT INTO api_keys (key_hash, worker, created_at) VALUES (?, ?, ?)",
        (hash_key(plaintext), worker, _now()),
    )
    conn.commit()
    return cur.lastrowid, plaintext


def verify(conn: sqlite3.Connection, key: str) -> dict | None:
    """Active key behind a plaintext key -> {id, worker, created_at}; else None.

    The worker identity in the row is what every job is attributed to. The
    hash never leaves this function, so callers cannot leak it downstream.
    """
    if not key or not key.startswith(config.KEY_PREFIX):
        return None
    digest = hash_key(key)
    for row in conn.execute("SELECT * FROM api_keys"):
        if hmac.compare_digest(row["key_hash"], digest):
            if row["revoked"]:
                return None
            return {name: row[name] for name in ("id", "worker", "created_at")}
    return None


def revoke_key(conn: sqlite3.Connection, key_id: int) -> bool:
    """Mark a key revoked (the row stays for job history); True if this call did it."""
    cur = conn.execute(
        "UPDATE api_keys SET revoked = 1 WHERE id = ? AND revoked = 0", (key_id,)
    )
    conn.commit()
    return cur.rowcount > 0
