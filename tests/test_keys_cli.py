import os
import pathlib
import re
import subprocess
import sys

import pytest

from app import auth, db, keys_cli

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ocr.db"))
    return tmp_path / "ocr.db"


@pytest.fixture
def conn(db_path):
    conn = db.connect(db_path)
    yield conn
    conn.close()


def run(argv):
    return keys_cli.main(argv)


# --- add ---


def test_add_prints_plaintext_exactly_once_with_copy_warning(db_path, capsys):
    assert run(["add", "ayse"]) == 0
    out = capsys.readouterr().out
    keys = re.findall(r"ocrk_[0-9a-f]{40}", out)
    assert len(keys) == 1
    assert "UYARI" in out and "kopyal" in out
    assert "ayse" in out


def test_add_stores_only_the_hash_and_verifies(db_path, capsys):
    run(["add", "ayse"])
    plaintext = re.search(r"ocrk_[0-9a-f]{40}", capsys.readouterr().out).group()
    conn = db.connect(db_path)
    row = conn.execute("SELECT * FROM api_keys").fetchone()
    assert row["worker"] == "ayse"
    assert row["key_hash"] == auth.hash_key(plaintext)
    assert auth.verify(conn, plaintext)["worker"] == "ayse"


def test_add_two_workers_gets_two_keys(db_path, capsys):
    assert run(["add", "ayse"]) == 0
    assert run(["add", "mehmet"]) == 0
    out = capsys.readouterr().out
    assert len(set(re.findall(r"ocrk_[0-9a-f]{40}", out))) == 2


def test_add_rejects_blank_worker(db_path, capsys):
    assert run(["add", "   "]) == 1
    assert "Hata" in capsys.readouterr().err
    assert not db.connect(db_path).execute("SELECT * FROM api_keys").fetchall()


# --- list ---


def test_list_on_empty_db_is_friendly(db_path, capsys):
    assert run(["list"]) == 0
    assert "yok" in capsys.readouterr().out


def test_list_shows_identities_never_secrets(db_path, capsys):
    run(["add", "ayse"])
    plaintext = re.search(r"ocrk_[0-9a-f]{40}", capsys.readouterr().out).group()
    assert run(["list"]) == 0
    out = capsys.readouterr().out
    assert "ayse" in out and "aktif" in out and "1" in out
    assert plaintext not in out
    assert auth.hash_key(plaintext) not in out


def test_list_marks_revoked_keys(db_path, capsys):
    run(["add", "ayse"])
    capsys.readouterr()
    run(["revoke", "1"])
    capsys.readouterr()
    assert run(["list"]) == 0
    out = capsys.readouterr().out
    assert "iptal" in out and "aktif" not in out


# --- revoke ---


def test_revoke_stops_the_key_immediately(db_path, capsys):
    run(["add", "ayse"])
    plaintext = re.search(
        r"ocrk_[0-9a-f]{40}", capsys.readouterr().out
    ).group()
    assert run(["revoke", "1"]) == 0
    assert "iptal edildi" in capsys.readouterr().out
    assert auth.verify(db.connect(db_path), plaintext) is None


def test_revoke_unknown_id_fails(db_path, capsys):
    assert run(["revoke", "42"]) == 1
    assert "Hata" in capsys.readouterr().err


def test_revoke_twice_fails_the_second_time(db_path, capsys):
    run(["add", "ayse"])
    capsys.readouterr()
    assert run(["revoke", "1"]) == 0
    assert run(["revoke", "1"]) == 1


# --- argument handling / module entry ---


def test_missing_command_exits_with_argparse_error(db_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run([])
    assert excinfo.value.code == 2


def test_non_numeric_key_id_exits_with_argparse_error(db_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run(["revoke", "abc"])
    assert excinfo.value.code == 2


def test_runs_as_a_module(db_path):
    env = {**os.environ, "DB_PATH": str(db_path), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-m", "app.keys_cli", "list"],
        cwd=ROOT,
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0
    assert "yok" in result.stdout.decode("utf-8")
