import pytest

from app import auth, config, db


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "ocr.db")
    auth._buckets.clear()
    yield conn
    conn.close()


@pytest.fixture
def bucket(conn, monkeypatch):
    """3 tokens, 1 token/s refill."""
    monkeypatch.setattr(config, "rate_capacity", lambda: 3)
    monkeypatch.setattr(config, "rate_refill_per_s", lambda: 1.0)


# --- 401: verify comes first, and costs nothing ---


def test_valid_key_is_allowed(conn):
    _, key = auth.create_key(conn, "ayse")
    status, row, retry = auth.authorize(conn, key, now=0.0)
    assert status == 200
    assert row["worker"] == "ayse"
    assert retry == 0.0


def test_authorize_works_on_the_real_clock(conn):
    _, key = auth.create_key(conn, "ayse")
    assert auth.authorize(conn, key)[0] == 200


@pytest.mark.parametrize("candidate", ["", " ", "nope", "ocrk_" + "0" * 40])
def test_missing_or_unknown_key_is_401(conn, candidate):
    auth.create_key(conn, "ayse")
    status, row, retry = auth.authorize(conn, candidate, now=0.0)
    assert (status, row, retry) == (401, None, 0.0)


def test_revoked_key_is_401(conn):
    key_id, key = auth.create_key(conn, "ayse")
    auth.revoke_key(conn, key_id)
    assert auth.authorize(conn, key, now=0.0)[0] == 401


def test_401s_never_consume_tokens(conn, bucket):
    _, key = auth.create_key(conn, "ayse")
    for _ in range(10):
        auth.authorize(conn, "ocrk_" + "0" * 40, now=0.0)
    assert [auth.authorize(conn, key, now=0.0)[0] for _ in range(3)] == [200] * 3
    assert auth.authorize(conn, key, now=0.0)[0] == 429


# --- 429: capacity, retry-after, refill ---


def test_capacity_from_config_then_429(conn, bucket):
    _, key = auth.create_key(conn, "ayse")
    assert [auth.authorize(conn, key, now=0.0)[0] for _ in range(3)] == [200] * 3
    status, row, retry = auth.authorize(conn, key, now=0.0)
    assert status == 429
    assert row["worker"] == "ayse"  # identity survives for attribution
    assert 0.0 < retry <= 1.0


def test_retry_after_shrinks_as_time_passes(conn, bucket):
    _, key = auth.create_key(conn, "ayse")
    for _ in range(3):
        auth.authorize(conn, key, now=0.0)
    assert auth.authorize(conn, key, now=0.0)[2] == pytest.approx(1.0)
    assert auth.authorize(conn, key, now=0.4)[2] == pytest.approx(0.6)


def test_refill_restores_service_one_token_at_a_time(conn, bucket):
    _, key = auth.create_key(conn, "ayse")
    for _ in range(3):
        auth.authorize(conn, key, now=0.0)
    assert auth.authorize(conn, key, now=0.5)[0] == 429
    assert auth.authorize(conn, key, now=1.0)[0] == 200
    assert auth.authorize(conn, key, now=1.0)[0] == 429


def test_tokens_never_accumulate_past_capacity(conn, bucket):
    _, key = auth.create_key(conn, "ayse")
    assert auth.authorize(conn, key, now=0.0)[0] == 200
    burst = [auth.authorize(conn, key, now=10_000.0)[0] for _ in range(4)]
    assert burst == [200, 200, 200, 429]


# --- buckets are per key ---


def test_exhausting_one_key_leaves_others_alone(conn, bucket):
    _, ayse = auth.create_key(conn, "ayse")
    _, mehmet = auth.create_key(conn, "mehmet")
    for _ in range(3):
        auth.authorize(conn, ayse, now=0.0)
    assert auth.authorize(conn, ayse, now=0.0)[0] == 429
    assert auth.authorize(conn, mehmet, now=0.0)[0] == 200


def test_capacity_change_is_read_per_request(conn, monkeypatch):
    monkeypatch.setattr(config, "rate_capacity", lambda: 1)
    monkeypatch.setattr(config, "rate_refill_per_s", lambda: 1.0)
    _, key = auth.create_key(conn, "ayse")
    assert auth.authorize(conn, key, now=0.0)[0] == 200
    assert auth.authorize(conn, key, now=0.0)[0] == 429
    monkeypatch.setattr(config, "rate_capacity", lambda: 5)
    assert auth.authorize(conn, key, now=1.0)[0] == 200
