import hashlib
import hmac
import re

import pytest

from app import auth, config, db

HEX64 = re.compile(r"[0-9a-f]{64}")


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "ocr.db")
    yield conn
    conn.close()


# --- generate / hash ---


def test_generate_key_shape():
    assert re.fullmatch(r"ocrk_[0-9a-f]{40}", auth.generate_key())


def test_generate_key_prefix_and_length_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "KEY_PREFIX", "tst_")
    monkeypatch.setattr(config, "KEY_BYTES", 8)
    assert re.fullmatch(r"tst_[0-9a-f]{16}", auth.generate_key())


def test_generated_keys_are_unique():
    assert len({auth.generate_key() for _ in range(50)}) == 50


def test_hash_key_is_sha256_hex():
    assert auth.hash_key("ocrk_abc") == hashlib.sha256(b"ocrk_abc").hexdigest()
    assert HEX64.fullmatch(auth.hash_key(""))


# --- create ---


def test_create_key_returns_id_and_plaintext_once(conn):
    key_id, plaintext = auth.create_key(conn, "ayse")
    row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    assert row["worker"] == "ayse"
    assert row["revoked"] == 0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:]+\.\d{3}Z", row["created_at"])
    assert auth.verify(conn, plaintext)["id"] == key_id


def test_create_key_stores_only_the_hash(conn):
    _, plaintext = auth.create_key(conn, "ayse")
    row = dict(conn.execute("SELECT * FROM api_keys").fetchone())
    assert row["key_hash"] == auth.hash_key(plaintext)
    assert plaintext not in row.values()


def test_create_key_gives_each_worker_its_own_key(conn):
    ayse_id, ayse = auth.create_key(conn, "ayse")
    mehmet_id, mehmet = auth.create_key(conn, "mehmet")
    assert ayse_id != mehmet_id
    assert ayse != mehmet
    assert auth.verify(conn, ayse)["worker"] == "ayse"
    assert auth.verify(conn, mehmet)["worker"] == "mehmet"


# --- verify ---


def test_verify_returns_identity_without_the_hash(conn):
    key_id, plaintext = auth.create_key(conn, "ayse")
    key = auth.verify(conn, plaintext)
    assert key == {"id": key_id, "worker": "ayse", "created_at": key["created_at"]}
    assert "key_hash" not in key


@pytest.mark.parametrize(
    "candidate",
    ["", " ", "nope", "ocrk_" + "0" * 40, "secret-scheme ocrk_" + "0" * 40],
)
def test_verify_rejects_missing_unknown_or_malformed_keys(conn, candidate):
    auth.create_key(conn, "ayse")
    assert auth.verify(conn, candidate) is None


def test_verify_rejects_tampered_key(conn):
    _, plaintext = auth.create_key(conn, "ayse")
    assert auth.verify(conn, plaintext[:-1]) is None
    assert auth.verify(conn, plaintext + "0") is None


def test_verify_finds_one_key_among_many(conn):
    keys = {worker: auth.create_key(conn, worker)[1] for worker in "abcdefgh"}
    assert auth.verify(conn, keys["d"])["worker"] == "d"
    assert auth.verify(conn, keys["h"])["worker"] == "h"


def test_verify_compares_only_hashes(conn, monkeypatch):
    _, plaintext = auth.create_key(conn, "ayse")
    seen = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert auth.verify(conn, plaintext) is not None
    assert seen, "verify must use hmac.compare_digest"
    for a, b in seen:
        assert HEX64.fullmatch(a) and HEX64.fullmatch(b)
        assert plaintext not in (a, b)


# --- revoke ---


def test_revoke_stops_verification_immediately(conn):
    key_id, plaintext = auth.create_key(conn, "ayse")
    _, mehmet_key = auth.create_key(conn, "mehmet")
    assert auth.revoke_key(conn, key_id) is True
    assert auth.verify(conn, plaintext) is None
    assert auth.verify(conn, mehmet_key)["worker"] == "mehmet"


def test_revoke_keeps_the_row_for_job_history(conn):
    key_id, _ = auth.create_key(conn, "ayse")
    auth.revoke_key(conn, key_id)
    row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    assert row["revoked"] == 1
    assert row["worker"] == "ayse"


def test_revoke_reports_unknown_and_already_revoked(conn):
    key_id, _ = auth.create_key(conn, "ayse")
    assert auth.revoke_key(conn, 9999) is False
    assert auth.revoke_key(conn, key_id) is True
    assert auth.revoke_key(conn, key_id) is False
