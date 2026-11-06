"""T40 — the status snapshot: service probes, VRAM, queue depth, Durum page.

The one promise every part rests on: a status read never raises. A server
that refuses the connection, an nvidia-smi that does not exist and a queue
that has never seen a job all answer with data — ok False, unavailable,
zeros — so the page can always render the machine as it really is.
"""
from __future__ import annotations

import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, db, status
from app.main import create_app

ANAHTAR = "yonetici-anahtari-e7a1"
VRAM = {"used_mb": 27000, "total_mb": 32768, "ok": True}
YOK_VRAM = {"used_mb": None, "total_mb": None, "ok": False}
GECERLI_ALANLAR = {"ocr", "strata", "unsloth", "vram", "queue"}


def tasima(acik_portlar: set[int]) -> httpx.MockTransport:
    """A transport answering /v1/models only on the ports that are open."""

    def elde(request: httpx.Request) -> httpx.Response:
        assert request.url.path == status.PROBE_PATH
        if request.url.port in acik_portlar:
            return httpx.Response(200, json={"data": []})
        raise httpx.ConnectError("connection refused")

    return httpx.MockTransport(elde)


# --- probe_service ---


def test_an_open_server_answers_ok_with_a_latency():
    sonuc = status.probe_service("http://127.0.0.1:8081", tasima({8081}))
    assert sonuc["ok"] is True
    assert isinstance(sonuc["latency_ms"], int)


def test_a_refused_port_reads_as_not_ok_and_never_raises():
    assert status.probe_service("http://127.0.0.1:8081", tasima(set())) == {
        "ok": False,
        "latency_ms": None,
    }


def test_a_server_answering_500_is_not_ok():
    kapali = httpx.MockTransport(lambda request: httpx.Response(500))
    assert status.probe_service("http://127.0.0.1:8081", kapali)["ok"] is False


# --- vram_info ---


def test_vram_reads_the_nvidia_smi_row(monkeypatch):
    def calinma(komut, **_):
        assert komut[0] == "nvidia-smi"
        return subprocess.CompletedProcess(komut, 0, "27000, 32768\n", "")

    monkeypatch.setattr(status.subprocess, "run", calinma)
    assert status.vram_info() == VRAM


def test_vram_without_the_tool_is_unavailable_not_an_error(monkeypatch):
    def calinma(*_, **__):
        raise FileNotFoundError("nvidia-smi bulunamadı")

    monkeypatch.setattr(status.subprocess, "run", calinma)
    assert status.vram_info() == YOK_VRAM


def test_vram_on_garbage_output_is_unavailable_too(monkeypatch):
    def calinma(komut, **_):
        return subprocess.CompletedProcess(komut, 1, "NVIDIA-SMI has failed\n", "")

    monkeypatch.setattr(status.subprocess, "run", calinma)
    assert status.vram_info() == YOK_VRAM


# --- queue depth ---


def test_queue_depth_counts_open_statuses_and_zeroes_the_rest(tmp_path):
    conn = db.connect(tmp_path / "ocr.db")
    for durum, adet in (("queued", 2), ("running", 1), ("failed", 3), ("done", 9)):
        for _ in range(adet):
            db.set_status(conn, db.create_job(conn)["id"], durum)
    assert db.queue_depth(conn) == {"queued": 2, "running": 1, "failed": 3}
    conn.close()


def test_queue_depth_of_an_empty_queue_is_three_zeros(tmp_path):
    conn = db.connect(tmp_path / "ocr.db")
    assert db.queue_depth(conn) == {"queued": 0, "running": 0, "failed": 0}
    conn.close()


# --- probe_all: the contract 9 payload ---


def test_probe_all_holds_the_contract_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "vram_info", lambda: VRAM)
    conn = db.connect(tmp_path / "ocr.db")
    db.set_status(conn, db.create_job(conn)["id"], "failed")
    govde = status.probe_all(conn, transport=tasima({8081, 8080}))
    conn.close()
    assert set(govde) == GECERLI_ALANLAR
    assert govde["ocr"]["ok"] is True and govde["strata"]["ok"] is True
    assert govde["unsloth"] == {"ok": False, "latency_ms": None}  # 8888 closed
    assert govde["vram"] == VRAM
    assert govde["queue"] == {"queued": 0, "running": 0, "failed": 1}


# --- the admin route ---


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A signed-in admin client; probes and nvidia-smi are canned, the queue is real."""
    auth._sessions.clear()
    auth._buckets.clear()
    monkeypatch.setenv("ADMIN_TOKEN", ANAHTAR)
    monkeypatch.setattr(status, "vram_info", lambda: VRAM)
    monkeypatch.setattr(
        status,
        "probe_service",
        lambda base_url, transport=None: {"ok": True, "latency_ms": 5},
    )
    path = tmp_path / "ocr.db"
    conn = db.connect(path)
    client = TestClient(create_app(db_path=path), raise_server_exceptions=False)
    assert client.post("/admin/api/login", json={"token": ANAHTAR}).status_code == 200
    yield client, conn
    conn.close()
    auth._sessions.clear()
    auth._buckets.clear()


def test_the_status_route_answers_the_contract_payload(env):
    client, conn = env
    db.set_status(conn, db.create_job(conn)["id"], "running")
    yanit = client.get("/admin/api/status")
    assert yanit.status_code == 200, yanit.text
    vucut = yanit.json()
    assert set(vucut) == GECERLI_ALANLAR
    assert vucut["ocr"] == {"ok": True, "latency_ms": 5}
    assert vucut["vram"] == VRAM
    assert vucut["queue"] == {"queued": 0, "running": 1, "failed": 0}


def test_the_status_route_survives_a_machine_without_nvidia_smi(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(status, "vram_info", lambda: YOK_VRAM)
    assert client.get("/admin/api/status").json()["vram"] == YOK_VRAM


def test_the_status_route_refuses_a_caller_without_a_session(tmp_path):
    client = TestClient(create_app(db_path=tmp_path / "ocr.db"))
    assert client.get("/admin/api/status").status_code == 401


# --- the page that draws it ---


def test_the_page_holds_the_status_controls(env):
    client, _ = env
    html = client.get("/admin/").text
    for kontrol in (
        "durum-yenile",
        "durum-hata",
        "durum-bekleme",
        "durum-icerik",
        "durum-servisler",
        "durum-vram",
        "durum-kuyruk",
        "durum-guncelleme",
    ):
        assert f'id="{kontrol}"' in html


def test_the_status_module_calls_the_admin_api(env):
    client, _ = env
    js = client.get("/admin/status.js")
    assert js.status_code == 200
    assert 'API = "/admin/api"' in js.text
    assert "/status" in js.text


# --- the stage-2 probe follows the configured backend (T85) ---


def adres_tutan(
    acik_portlar: set[int],
) -> tuple[httpx.MockTransport, list[str]]:
    """Like tasima, but also records every full url the probes asked for."""
    gorulen: list[str] = []

    def elde(request: httpx.Request) -> httpx.Response:
        gorulen.append(str(request.url))
        if request.url.port in acik_portlar:
            return httpx.Response(200, json={"data": []})
        raise httpx.ConnectError("connection refused")

    return httpx.MockTransport(elde), gorulen


def anlik_govde(tmp_path, monkeypatch, tasima) -> dict:
    monkeypatch.setattr(status, "vram_info", lambda: YOK_VRAM)
    conn = db.connect(tmp_path / "ocr.db")
    govde = status.probe_all(conn, transport=tasima)
    conn.close()
    return govde


def test_the_small_backend_probes_the_small_brain_on_8100(tmp_path, monkeypatch):
    """STRUCTURER_BACKEND=small: contract 9's "strata" key is the small brain."""
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    tasima, gorulen = adres_tutan({8081, 8100})
    govde = anlik_govde(tmp_path, monkeypatch, tasima)
    assert "http://127.0.0.1:8100/v1/models" in gorulen
    assert "http://127.0.0.1:8080/v1/models" not in gorulen
    assert govde["strata"]["ok"] is True  # the CPU-only box's green stage-2 chip


def test_the_strata_backend_still_probes_strata(tmp_path, monkeypatch):
    monkeypatch.delenv("STRUCTURER_BACKEND", raising=False)
    tasima, gorulen = adres_tutan({8081, 8080})
    govde = anlik_govde(tmp_path, monkeypatch, tasima)
    assert "http://127.0.0.1:8080/v1/models" in gorulen
    assert "http://127.0.0.1:8100/v1/models" not in gorulen
    assert govde["strata"]["ok"] is True


def test_stage2_base_url_names_the_configured_brain(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    assert status.stage2_base_url() == "http://127.0.0.1:8100"
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    assert status.stage2_base_url() == "http://127.0.0.1:8080"


@pytest.mark.parametrize("backend", ["small", "strata"])
def test_the_payload_keys_did_not_change(backend, tmp_path, monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", backend)
    govde = anlik_govde(tmp_path, monkeypatch, adres_tutan(set())[0])
    assert list(govde) == ["ocr", "strata", "unsloth", "vram", "queue"]
    for servis in ("ocr", "strata", "unsloth"):
        assert govde[servis] == {"ok": False, "latency_ms": None}
    assert govde["vram"] == YOK_VRAM
    assert govde["queue"] == {"queued": 0, "running": 0, "failed": 0}
