import os
import pathlib
import re

import pytest

from app import config

OWN_PREFIXES = (
    "APP_",
    "OCR_",
    "STRATA_",
    "UNSLOTH_",
    "PROBE_",
    "STARTUP_",
    "ADMIN_",
    "RATE_",
    "DATA_DIR",
    "DB_PATH",
    "MAX_UPLOAD",
    "IMAGE_",
    "THUMB_",
    "JPEG_",
    "LLAMA_",
    "STALE_",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in [n for n in os.environ if n.startswith(OWN_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)


def set_env(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))


def test_defaults_match_brief():
    assert config.app_port() == 8090
    assert config.ocr_port() == 8081
    assert config.strata_port() == 8080
    assert config.unsloth_port() == 8888
    assert config.ocr_ngl() == 0
    assert config.app_host() == config.ocr_host() == "127.0.0.1"
    assert config.ocr_timeout() == 120.0
    assert config.structurer_timeout() == 120.0
    assert config.probe_timeout() == 2.0
    assert config.startup_wait_s() == 60
    assert config.rate_capacity() == 20
    assert config.rate_refill_per_s() == 5.0
    assert config.admin_session_hours() == 12.0
    assert config.max_upload_mb() == 15
    assert config.image_max_edge() == 1600
    assert config.thumb_max_edge() == 240
    assert config.jpeg_quality() == 85
    assert config.stale_job_minutes() == 10
    assert config.CURRENCY == "TRY"


def test_no_secret_hardcoded():
    assert config.admin_token() == ""
    stored = [
        name
        for name in dir(config)
        if name.isupper() and any(w in name for w in ("TOKEN", "SECRET", "PASSWORD"))
    ]
    assert stored == []


def test_base_urls_follow_host_and_port(monkeypatch):
    set_env(monkeypatch, APP_HOST="0.0.0.0", APP_PORT=9000, OCR_HOST="10.0.0.5", OCR_PORT=8123)
    assert config.app_base_url() == "http://0.0.0.0:9000"
    assert config.ocr_base_url() == "http://10.0.0.5:8123"
    assert config.strata_base_url() == "http://127.0.0.1:8080"
    assert config.unsloth_base_url() == "http://127.0.0.1:8888"


def test_typed_getters_parse_env(monkeypatch):
    set_env(
        monkeypatch,
        OCR_PORT=9,
        OCR_TIMEOUT_S="3.5",
        RATE_LIMIT_REFILL_PER_S="0.25",
        OCR_NGL=35,
        ADMIN_TOKEN="s3cret",
        STALE_JOB_MINUTES=0,
    )
    assert config.ocr_port() == 9
    assert isinstance(config.ocr_port(), int)
    assert config.ocr_timeout() == 3.5
    assert config.rate_refill_per_s() == 0.25
    assert config.ocr_ngl() == 35
    assert config.admin_token() == "s3cret"
    assert config.stale_job_minutes() == 0


def test_blank_or_whitespace_counts_as_unset(monkeypatch):
    set_env(monkeypatch, OCR_PORT="   ", ADMIN_TOKEN="", APP_HOST="  ")
    assert config.ocr_port() == 8081
    assert config.admin_token() == ""
    assert config.app_host() == "127.0.0.1"


def test_values_surrounding_whitespace_are_trimmed(monkeypatch):
    set_env(monkeypatch, STRATA_MODEL="  strata-q  ", OCR_PORT=" 8123 ")
    assert config.strata_model() == "strata-q"
    assert config.ocr_port() == 8123


def test_unparsable_values_fall_back_to_default(monkeypatch):
    set_env(monkeypatch, OCR_PORT="notaport", OCR_TIMEOUT_S="soon", RATE_LIMIT_CAPACITY="many")
    assert config.ocr_port() == 8081
    assert config.ocr_timeout() == 120.0
    assert config.rate_capacity() == 20


def test_data_dir_defaults_under_project_root():
    assert config.data_dir() == config.ROOT / "data"
    assert config.images_dir() == config.ROOT / "data" / "images"
    assert config.db_path() == config.ROOT / "data" / "ocr.db"
    assert config.log_dir() == config.ROOT / "data" / "logs"


def test_relative_data_dir_resolves_against_root(monkeypatch):
    set_env(monkeypatch, DATA_DIR="tmp/ocr-data")
    assert config.data_dir() == config.ROOT / "tmp" / "ocr-data"
    assert config.images_dir() == config.ROOT / "tmp" / "ocr-data" / "images"
    assert config.db_path() == config.ROOT / "tmp" / "ocr-data" / "ocr.db"


def test_absolute_data_dir_is_kept(monkeypatch, tmp_path):
    set_env(monkeypatch, DATA_DIR=tmp_path / "storage")
    assert config.data_dir() == tmp_path / "storage"
    assert config.db_path() == tmp_path / "storage" / "ocr.db"


def test_db_path_can_be_overridden_independently(monkeypatch, tmp_path):
    set_env(monkeypatch, DB_PATH=tmp_path / "jobs.db")
    assert config.db_path() == tmp_path / "jobs.db"
    assert config.images_dir() == config.ROOT / "data" / "images"


def test_home_relative_path_is_expanded(monkeypatch):
    set_env(monkeypatch, OCR_MODEL="~/models/paddle.gguf")
    path = config.ocr_model_path()
    assert path.is_absolute() and "~" not in str(path)
    assert path.name == "paddle.gguf"


def test_model_paths_point_at_the_spike_ggufs():
    assert config.ocr_model_path().name == "PaddleOCR-VL-1.6-GGUF.gguf"
    assert config.ocr_mmproj_path().name == "PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
    assert config.llama_server_path() == config.ROOT / "vendor" / "llama" / "llama-server.exe"


def test_key_prefix_shape():
    assert re.fullmatch(r"ocrk_[0-9a-f]{40}", f"{config.KEY_PREFIX}{'0' * 40}")
    assert config.KEY_BYTES * 2 == 40


def test_config_reads_env_only_through_helpers():
    source = pathlib.Path(config.__file__).read_text(encoding="utf-8")
    assert source.count("os.environ.get(") == 1
