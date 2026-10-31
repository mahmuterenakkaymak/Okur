"""Every tunable in one place: env var -> typed value with a safe default.

No other module reads os.environ. Secrets (ADMIN_TOKEN) have no non-empty
default and are never hardcoded; they come from the environment or the
gitignored .env next to the project root.
"""
from __future__ import annotations

import os
import pathlib

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

KEY_PREFIX = "ocrk_"
KEY_BYTES = 20  # -> ocrk_<40 hex>
CURRENCY = "TRY"


def _raw(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def env_str(name: str, default: str = "") -> str:
    raw = _raw(name)
    return default if raw is None else raw


def env_int(name: str, default: int) -> int:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_path(name: str, default: str | os.PathLike[str]) -> pathlib.Path:
    """Path tunable; a relative value is resolved against the project root."""
    raw = _raw(name)
    if raw is None:
        return pathlib.Path(default)
    path = pathlib.Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


# --- app ---
def app_host() -> str:
    return env_str("APP_HOST", "127.0.0.1")


def app_port() -> int:
    return env_int("APP_PORT", 8090)


def app_base_url() -> str:
    return _base_url(app_host(), app_port())


# --- stage 1: OCR (llama.cpp llama-server) ---
def ocr_host() -> str:
    return env_str("OCR_HOST", "127.0.0.1")


def ocr_port() -> int:
    return env_int("OCR_PORT", 8081)


def ocr_base_url() -> str:
    return _base_url(ocr_host(), ocr_port())


def ocr_model_name() -> str:
    return env_str("OCR_MODEL_NAME", "PaddleOCR-VL-1.6")


def ocr_model_path() -> pathlib.Path:
    return env_path("OCR_MODEL", ROOT / "models/paddleocr-vl-1.6/PaddleOCR-VL-1.6-GGUF.gguf")


def ocr_mmproj_path() -> pathlib.Path:
    return env_path(
        "OCR_MMPROJ", ROOT / "models/paddleocr-vl-1.6/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
    )


def ocr_chat_template_path() -> pathlib.Path:
    """The GGUF ships its chat template as a sibling .jinja; llama-server
    takes it through --chat-template-file (run.py)."""
    return env_path("OCR_CHAT_TEMPLATE", ocr_model_path().with_name("chat_template.jinja"))


def llama_server_path() -> pathlib.Path:
    return env_path("LLAMA_SERVER", ROOT / "vendor/llama/llama-server.exe")


def ocr_ngl() -> int:
    """GPU layers: 0 = CPU, so OCR coexists with Strata on the 32 GB card."""
    return env_int("OCR_NGL", 0)


def ocr_ctx() -> int:
    return env_int("OCR_CTX", 4096)


# --- stage 2: structuring (Strata, quality mode: Unsloth Studio) ---
def strata_host() -> str:
    return env_str("STRATA_HOST", "127.0.0.1")


def strata_port() -> int:
    return env_int("STRATA_PORT", 8080)


def strata_base_url() -> str:
    return _base_url(strata_host(), strata_port())


def strata_model() -> str:
    return env_str("STRATA_MODEL", "strata")


def unsloth_host() -> str:
    return env_str("UNSLOTH_HOST", "127.0.0.1")


def unsloth_port() -> int:
    return env_int("UNSLOTH_PORT", 8888)


def unsloth_base_url() -> str:
    return _base_url(unsloth_host(), unsloth_port())


def unsloth_model() -> str:
    # ASSUMPTION: server-side model labels for stage 2 are not fixed by the
    # contract; both are env-overridable and only echoed into meta.model.
    return env_str("UNSLOTH_MODEL", "Qwen3.8-27B")


# --- HTTP timeouts (seconds) ---
def ocr_timeout() -> float:
    return env_float("OCR_TIMEOUT_S", 120.0)


def structurer_timeout() -> float:
    return env_float("STRUCTURER_TIMEOUT_S", 120.0)


def probe_timeout() -> float:
    return env_float("PROBE_TIMEOUT_S", 2.0)


def startup_wait_s() -> int:
    return env_int("STARTUP_WAIT_S", 60)


# --- auth, admin, rate limit ---
def admin_token() -> str:
    return env_str("ADMIN_TOKEN", "")


def admin_session_hours() -> float:
    return env_float("ADMIN_SESSION_HOURS", 12.0)


def rate_capacity() -> int:
    return env_int("RATE_LIMIT_CAPACITY", 20)


def rate_refill_per_s() -> float:
    return env_float("RATE_LIMIT_REFILL_PER_S", 5.0)


# --- storage ---
def data_dir() -> pathlib.Path:
    return env_path("DATA_DIR", ROOT / "data")


def images_dir() -> pathlib.Path:
    return data_dir() / "images"


def db_path() -> pathlib.Path:
    return env_path("DB_PATH", data_dir() / "ocr.db")


def log_dir() -> pathlib.Path:
    return data_dir() / "logs"


# --- uploads and images ---
def max_upload_mb() -> int:
    return env_int("MAX_UPLOAD_MB", 15)


def image_max_edge() -> int:
    return env_int("IMAGE_MAX_EDGE", 1600)


def thumb_max_edge() -> int:
    return env_int("THUMB_MAX_EDGE", 240)


def jpeg_quality() -> int:
    return env_int("JPEG_QUALITY", 85)


# --- queue ---
def stale_job_minutes() -> int:
    return env_int("STALE_JOB_MINUTES", 10)
