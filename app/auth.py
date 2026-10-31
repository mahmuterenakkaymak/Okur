"""Worker API keys: ocrk_<40 hex>, SHA-256 at rest, constant-time verify.

The plaintext leaves create_key once and is never written down: the database
holds only the hash, so a stolen ocr.db cannot be replayed as a key. verify()
hashes the candidate and compares hashes with hmac.compare_digest, and a
revoked key stops resolving on the next call.

Admin sessions follow the same rule one level up: ADMIN_TOKEN is compared in
constant time and never leaves the server — login hands back a random session
id, and that id alone is what the httpOnly cookie carries.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time

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


# --- rate limit ---

# ASSUMPTION: the HTTP layer arrives in T15; authorize() returns the status
# code (401/429/200) its middleware maps straight onto a response.
# ASSUMPTION: buckets live in this process only — PLAN.md runs one app
# process, so a restart (empty buckets) is the only reset.

_lock = threading.Lock()
_buckets: dict[int, tuple[float, float]] = {}  # key_id -> (tokens, last_s)


def authorize(
    conn: sqlite3.Connection, key: str, *, now: float | None = None
) -> tuple[int, dict | None, float]:
    """Verify + per-key token bucket: (status, key row, retry-after seconds).

    401 for a missing, unknown or revoked key (no token consumed), 429 with
    the wait until the next token when the bucket is empty, 200 otherwise.
    The row comes back on 429 too, so the caller can still attribute the hit.
    """
    row = verify(conn, key)
    if row is None:
        return 401, None, 0.0
    if now is None:
        now = time.monotonic()
    retry_after = _take_token(row["id"], now)
    if retry_after > 0.0:
        return 429, row, retry_after
    return 200, row, 0.0


def _take_token(key_id: int, now: float) -> float:
    """Consume one token if the bucket has it; else seconds until the next."""
    capacity = float(config.rate_capacity())
    refill = config.rate_refill_per_s()
    with _lock:
        tokens, last = _buckets.get(key_id, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * refill)
        _buckets[key_id] = (tokens - 1.0 if tokens >= 1.0 else tokens, now)
        return 0.0 if tokens >= 1.0 else (1.0 - tokens) / refill


# --- admin sessions ---

# ASSUMPTION: sessions live in this process only — PLAN.md runs one app
# process, so a restart signs the operator out, the safe direction to fail.
ADMIN_COOKIE = "ocr_admin_session"
_sessions: dict[str, float] = {}  # session id -> monotonic expiry


def admin_configured() -> bool:
    """False when ADMIN_TOKEN is unset: the admin panel has no door at all."""
    return bool(config.admin_token())


def admin_token_ok(candidate: str) -> bool:
    """Constant-time ADMIN_TOKEN check; an unset token matches nothing.

    Both sides go to bytes first: hmac.compare_digest rejects non-ASCII str,
    and a pasted token is whatever the operator typed.
    """
    expected = config.admin_token()
    if not expected or not candidate:
        return False
    return hmac.compare_digest(
        expected.encode("utf-8"), candidate.encode("utf-8")
    )


def start_session() -> str:
    """New session id for the httpOnly cookie — never the token itself."""
    now = time.monotonic()
    session_id = secrets.token_urlsafe(32)
    with _lock:
        for stale in [sid for sid, end in _sessions.items() if end <= now]:
            _sessions.pop(stale, None)
        _sessions[session_id] = now + config.admin_session_hours() * 3600.0
    return session_id


def session_ok(session_id: str) -> bool:
    """Live session id -> True; unknown or expired -> False (and forgotten)."""
    if not session_id:
        return False
    now = time.monotonic()
    with _lock:
        end = _sessions.get(session_id)
        if end is None:
            return False
        if end <= now:
            _sessions.pop(session_id, None)
            return False
        return True


def end_session(session_id: str) -> None:
    """Log out one session; logging out twice is not an error."""
    with _lock:
        _sessions.pop(session_id, None)
