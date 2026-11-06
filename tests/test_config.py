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
    "SMALL_BRAIN_",
    "STRUCTURER_",
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


def test_stage2_backend_defaults_to_strata():
    assert config.structurer_backend() == "strata"
    assert config.DEFAULT_STRUCTURER_BACKEND == "strata"


def test_small_brain_defaults():
    assert config.small_brain_base_url() == "http://127.0.0.1:8100"
    assert config.small_brain_port() == 8100
    assert isinstance(config.small_brain_port(), int)
    assert config.small_brain_model() == "Qwen3-VL-4B-Instruct"
    assert config.structurer_include_image() is True


def test_stage2_model_names_the_running_brain(monkeypatch):
    assert config.stage2_model(False) == config.strata_model() == "strata"
    assert config.stage2_model(True) == config.unsloth_model() == "Qwen3.8-27B"
    set_env(monkeypatch, STRUCTURER_BACKEND="small")
    assert config.stage2_model(False) == config.small_brain_model()
    # quality mode always escalates to Unsloth, whatever the backend says
    assert config.stage2_model(True) == config.unsloth_model()


def test_stage2_model_follows_model_env_overrides(monkeypatch):
    set_env(monkeypatch, STRATA_MODEL="strata-80b", UNSLOTH_MODEL="qwen-27b")
    assert config.stage2_model(False) == "strata-80b"
    assert config.stage2_model(True) == "qwen-27b"
    set_env(monkeypatch, STRUCTURER_BACKEND="small", SMALL_BRAIN_MODEL="vl-4b-iq4")
    assert config.stage2_model(False) == "vl-4b-iq4"
    assert config.stage2_model(True) == "qwen-27b"


def test_backend_env_override_is_case_insensitive(monkeypatch):
    set_env(monkeypatch, STRUCTURER_BACKEND="SMALL")
    assert config.structurer_backend() == "small"
    set_env(monkeypatch, STRUCTURER_BACKEND="Strata")
    assert config.structurer_backend() == "strata"


def test_small_brain_base_url_override_carries_the_port(monkeypatch):
    set_env(monkeypatch, SMALL_BRAIN_BASE_URL="http://10.0.0.5:9111/v1")
    assert config.small_brain_base_url() == "http://10.0.0.5:9111/v1"
    assert config.small_brain_port() == 9111


def test_include_image_truthy_and_falsy_values(monkeypatch):
    for value in ("0", "false", "FALSE", " no ", "off"):
        set_env(monkeypatch, STRUCTURER_INCLUDE_IMAGE=value)
        assert config.structurer_include_image() is False, value
    for value in ("1", "true", "Yes", "on"):
        set_env(monkeypatch, STRUCTURER_INCLUDE_IMAGE=value)
        assert config.structurer_include_image() is True, value


def test_stage2_keys_treat_whitespace_as_unset(monkeypatch):
    set_env(monkeypatch, STRUCTURER_BACKEND="   ", SMALL_BRAIN_BASE_URL="  ", SMALL_BRAIN_MODEL="")
    assert config.structurer_backend() == config.DEFAULT_STRUCTURER_BACKEND
    assert config.small_brain_base_url() == "http://127.0.0.1:8100"
    assert config.small_brain_model() == "Qwen3-VL-4B-Instruct"


def test_stage2_keys_fall_back_on_junk_values(monkeypatch):
    set_env(monkeypatch, STRUCTURER_BACKEND="q8", SMALL_BRAIN_BASE_URL="http://brain:abc")
    assert config.structurer_backend() == config.DEFAULT_STRUCTURER_BACKEND
    assert config.small_brain_port() == 8100
    set_env(monkeypatch, SMALL_BRAIN_BASE_URL="not a url")
    assert config.small_brain_port() == 8100
    set_env(monkeypatch, STRUCTURER_INCLUDE_IMAGE="maybe")
    assert config.structurer_include_image() is True


def install_small_brain(root: pathlib.Path, *, skip: str = "") -> pathlib.Path:
    """Create the three installed files, leaving out the one named in `skip`
    ("server", "model" or "mmproj")."""
    paths = {
        "server": root / "llama" / "llama-server.exe",
        "model": root / "models" / config.DEFAULT_SMALL_BRAIN_MODEL_FILE,
        "mmproj": root / "models" / config.DEFAULT_SMALL_BRAIN_MMPROJ_FILE,
    }
    for name, path in paths.items():
        if name != skip:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
    return root


def test_small_brain_dir_defaults_under_localappdata(monkeypatch, tmp_path):
    set_env(monkeypatch, LOCALAPPDATA=tmp_path)
    brain = tmp_path / "ocr-small-brain"
    assert config.small_brain_dir() == brain
    assert config.small_brain_server_path() == brain / "llama" / "llama-server.exe"
    model = config.small_brain_model_path()
    mmproj = config.small_brain_mmproj_path()
    assert model.parent == brain / "models" and model.suffix == ".gguf"
    assert mmproj.parent == brain / "models" and mmproj.suffix == ".gguf"


def test_small_brain_dir_env_override_moves_every_file(monkeypatch, tmp_path):
    set_env(monkeypatch, LOCALAPPDATA=tmp_path / "ignored", OCR_SMALL_BRAIN_DIR=tmp_path / "brain")
    assert config.small_brain_dir() == tmp_path / "brain"
    assert config.small_brain_server_path() == tmp_path / "brain" / "llama" / "llama-server.exe"
    assert (tmp_path / "brain" / "models").name in config.small_brain_model_path().parts
    assert config.small_brain_mmproj_path().parent == tmp_path / "brain" / "models"


def test_small_brain_file_env_overrides(monkeypatch, tmp_path):
    brain = install_small_brain(tmp_path / "brain")
    set_env(
        monkeypatch,
        OCR_SMALL_BRAIN_DIR=brain,
        SMALL_BRAIN_SERVER=tmp_path / "elsewhere" / "llama-server.exe",
        SMALL_BRAIN_MODEL_FILE=brain / "models" / "other-quant.gguf",
        SMALL_BRAIN_MMPROJ=brain / "models" / "other-mmproj.gguf",
    )
    assert config.small_brain_server_path() == tmp_path / "elsewhere" / "llama-server.exe"
    assert config.small_brain_model_path() == brain / "models" / "other-quant.gguf"
    assert config.small_brain_mmproj_path() == brain / "models" / "other-mmproj.gguf"


def test_small_brain_ready_needs_all_three_files(monkeypatch, tmp_path):
    set_env(monkeypatch, OCR_SMALL_BRAIN_DIR=tmp_path / "brain")
    assert config.small_brain_ready() is False
    install_small_brain(tmp_path / "brain")
    assert config.small_brain_ready() is True


@pytest.mark.parametrize("missing", ["server", "model", "mmproj"])
def test_small_brain_ready_false_when_one_file_is_missing(monkeypatch, tmp_path, missing):
    install_small_brain(tmp_path / "brain", skip=missing)
    set_env(monkeypatch, OCR_SMALL_BRAIN_DIR=tmp_path / "brain")
    assert config.small_brain_ready() is False
    missing_path = {
        "server": config.small_brain_server_path,
        "model": config.small_brain_model_path,
        "mmproj": config.small_brain_mmproj_path,
    }[missing]()
    assert missing_path.is_file() is False


def test_small_brain_ready_false_when_a_path_is_a_directory(monkeypatch, tmp_path):
    install_small_brain(tmp_path / "brain")
    set_env(monkeypatch, OCR_SMALL_BRAIN_DIR=tmp_path / "brain")
    config.small_brain_model_path().unlink()
    config.small_brain_model_path().mkdir()
    assert config.small_brain_ready() is False


def test_key_prefix_shape():
    assert re.fullmatch(r"ocrk_[0-9a-f]{40}", f"{config.KEY_PREFIX}{'0' * 40}")
    assert config.KEY_BYTES * 2 == 40


def test_config_reads_env_only_through_helpers():
    source = pathlib.Path(config.__file__).read_text(encoding="utf-8")
    assert source.count("os.environ.get(") == 1
