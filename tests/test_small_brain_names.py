"""T97: the installed weight is named for the quant its bytes actually are.

scripts/small_brain_manifest.json downloads `Qwen3-VL-4B-Instruct-IQ4_XS.gguf` from
the unsloth HF repo — the very file the bake-off measured (`vl4b_img`,
spike/SMALL_BRAIN_BAKEOFF.md). It used to be promoted under a `UD-IQ4_XS` name that
repo does not serve, so the file on disk claimed a quant it is not and PLAN,
OPERATIONS and the M8 gates named weights nobody can install. Pinned here: the name
the URL serves, the name that lands on disk and the name app/config.py looks for are
one and the same — while the *served model id* (`SMALL_BRAIN_MODEL`) stays the repo's
model name, quant-free, because that is what llama.cpp echoes into meta.model.
"""
import json
import pathlib

from app import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "small_brain_manifest.json"
SCRIPT = ROOT / "scripts" / "install_small_brain.ps1"
PLAN = ROOT / "PLAN.md"

rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
row_by_id = {row["id"]: row for row in rows}
model_row = row_by_id["qwen3-vl-4b-iq4-xs"]
# The name the CDN serves: nothing the installer invents.
served_name = model_row["url"].rsplit("/", 1)[-1]


def strip_env(monkeypatch, tmp_path) -> None:
    """A box whose only small-brain setting is a fake %LOCALAPPDATA%."""
    for name in (
        "OCR_SMALL_BRAIN_DIR",
        "SMALL_BRAIN_SERVER",
        "SMALL_BRAIN_MODEL_FILE",
        "SMALL_BRAIN_MMPROJ",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_the_url_and_its_mirror_serve_the_iq4_xs_the_bake_off_measured():
    assert served_name == "Qwen3-VL-4B-Instruct-IQ4_XS.gguf"
    assert model_row["mirror_url"].rsplit("/", 1)[-1] == served_name


def test_the_file_lands_under_the_name_the_url_serves():
    """No rename on install: dest's basename is the served file name."""
    assert model_row["dest"].replace("\\", "/").rsplit("/", 1)[-1] == served_name


def test_config_looks_for_that_same_file(monkeypatch, tmp_path):
    strip_env(monkeypatch, tmp_path)
    assert config.DEFAULT_SMALL_BRAIN_MODEL_FILE == served_name
    dest = pathlib.Path(model_row["dest"].replace("\\", "/"))
    assert config.small_brain_model_path() == config.small_brain_dir() / dest


def test_no_text_names_a_quant_the_repo_does_not_serve():
    for path in (MANIFEST, SCRIPT, PLAN, pathlib.Path(config.__file__)):
        text = path.read_text(encoding="utf-8-sig")
        assert "UD-IQ4_XS" not in text, path.name


def test_plan_names_the_quant_it_installed():
    assert "Qwen3-VL-4B-Instruct IQ4_XS" in PLAN.read_text(encoding="utf-8")


def test_the_served_model_id_stays_quant_free(monkeypatch):
    """meta.model keeps the served model id; only the file name carries a quant."""
    monkeypatch.delenv("SMALL_BRAIN_MODEL", raising=False)
    model_id = config.small_brain_model()
    assert model_id == "Qwen3-VL-4B-Instruct"
    assert served_name.startswith(model_id) and served_name != f"{model_id}.gguf"
