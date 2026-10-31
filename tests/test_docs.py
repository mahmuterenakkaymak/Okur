"""T49: README.md and OPERATIONS.md — the sections a reader needs, commands that exist.

Docs are an interface, so they are tested like one: every promised heading is
present, every script a doc names is a file in the repo, every flag it names is
a flag that script parses, and every default it quotes is the default
app/config.py really uses. Nothing here runs a documented command — a doc test
must not start a server, create a key or touch the tailnet.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

import run as launcher
from app import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
OPERATIONS = (ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
DOCS = {"README.md": README, "OPERATIONS.md": OPERATIONS}

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)
_TRAILING_COMMENT = re.compile(r"\s+#.*$")
_ENV_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.M)
_SCRIPT_MENTION = re.compile(r"scripts[/\\]([\w.-]+\.(?:py|ps1))")
_PS_FLAG = re.compile(r"^-(\w+)$")


def headings(text: str, level: int = 2) -> list[str]:
    mark = "#" * level + " "
    return [line[len(mark):].strip() for line in text.splitlines() if line.startswith(mark)]


def section(text: str, prefix: str, level: int = 2) -> str:
    """One section's body, from its heading to the next heading of that level."""
    mark = "#" * level + " "
    body, inside, found = [], False, False
    for line in text.splitlines():
        if line.startswith(mark):
            title = line[len(mark):].strip().lower()
            inside = title.startswith(prefix.lower())
            found = found or inside
            continue
        if inside:
            body.append(line)
    assert found, f"no section starting with {prefix!r}"
    return "\n".join(body)


def code_lines(text: str) -> list[str]:
    """Every non-comment line inside a fenced block, trailing comments stripped."""
    lines = []
    for _, block in _FENCE.findall(text):
        for raw in block.splitlines():
            line = _TRAILING_COMMENT.sub("", raw).strip()
            if line and not line.startswith("#"):
                lines.append(line)
    return lines


def repo_path(token: str) -> pathlib.Path:
    relative = token.replace("\\", "/")
    relative = re.sub(r"^\./", "", relative)
    return ROOT / relative


def python_commands() -> list[str]:
    return [
        line
        for text in DOCS.values()
        for line in code_lines(text)
        if "python" in line.split()[0].lower()
    ]


def powershell_commands() -> list[str]:
    return [
        line
        for text in DOCS.values()
        for line in code_lines(text)
        if line.split()[0].lower().endswith(".ps1")
    ]


def env_names() -> list[str]:
    names = []
    for text in DOCS.values():
        for lang, block in _FENCE.findall(text):
            if lang != "env":
                continue
            names += _ENV_ASSIGN.findall(block)
    return names


# --- required sections -------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    ["What it is", "Quickstart", "PWA install", "Integrator guide", "Tailscale",
     "Troubleshooting", "Operations"],
)
def test_readme_has_every_required_section(title: str):
    assert any(h.lower().startswith(title.lower()) for h in headings(README))


@pytest.mark.parametrize(
    "title", ["Backup", "Key rotation", "Log locations", "Model paths", "VRAM notes"]
)
def test_operations_has_every_required_section(title: str):
    assert any(h.lower().startswith(title.lower()) for h in headings(OPERATIONS))


def test_what_it_is_names_the_stages_and_who_owns_the_arithmetic():
    body = section(README, "What it is")
    for detail in ["PaddleOCR", "Strata", "validator", "verdict"]:
        assert detail in body


def test_integrator_guide_points_at_contract_md_and_the_openapi_ui():
    body = section(README, "Integrator guide")
    assert "CONTRACT.md" in body
    assert "/docs" in body
    assert "X-API-Key" in body


def test_pwa_install_section_installs_from_the_app_url_and_sets_the_key():
    body = section(README, "PWA install")
    for detail in ["/app", "API anahtarı", "HTTPS"]:
        assert detail in body


def test_troubleshooting_answers_the_status_codes_the_app_gives_out():
    body = section(README, "Troubleshooting")
    for detail in ["401", "429", "413", "queued", "data/logs"]:
        assert detail in body


def test_operations_backups_cover_everything_under_data():
    body = section(OPERATIONS, "Backup")
    for detail in ["ocr.db", "-wal", "images", "certs", "run.py --stop"]:
        assert detail in body


def test_key_rotation_covers_the_worker_keys_and_the_admin_token():
    body = section(OPERATIONS, "Key rotation")
    assert "keys_cli revoke" in body
    assert "ADMIN_TOKEN" in body


def test_log_section_names_the_files_the_launcher_actually_writes():
    for name in launcher.SERVICES:
        assert launcher.log_path(name).name in section(OPERATIONS, "Log locations")


def test_vram_notes_keep_stage_one_on_the_cpu():
    body = section(OPERATIONS, "VRAM notes")
    for detail in ["-ngl 0", "32 GB", "nvidia-smi", "OCR_NGL"]:
        assert detail in body


def test_readme_hands_the_operator_to_operations():
    assert "OPERATIONS.md" in README


# --- documented commands exist ----------------------------------------------

@pytest.mark.parametrize("command", python_commands(), ids=lambda c: c[:60])
def test_documented_python_command_names_something_real(command: str):
    tokens = command.split()
    if tokens[1] == "-m":
        # ASSUMPTION: a -m target is checked for importability only; its own
        # flags (pytest's -q) belong to a tool this repo does not own.
        assert importlib.util.find_spec(tokens[2]), f"{tokens[2]} is not importable"
        return
    script = repo_path(tokens[1])
    assert script.is_file(), f"{command!r} runs a file that does not exist"


@pytest.mark.parametrize("command", python_commands(), ids=lambda c: c[:60])
def test_documented_flags_are_flags_the_script_parses(command: str):
    tokens = command.split()
    if tokens[1] == "-m":
        return
    script = repo_path(tokens[1])
    if not script.is_file():
        pytest.fail(f"{command!r} runs a file that does not exist")
    source = script.read_text(encoding="utf-8")
    for flag in (t for t in tokens[2:] if t.startswith("--")):
        assert f'"{flag}"' in source or f"'{flag}'" in source, (
            f"{flag} is documented but {script.name} never parses it"
        )


@pytest.mark.parametrize("command", powershell_commands(), ids=lambda c: c[:60])
def test_documented_powershell_command_and_its_parameters_exist(command: str):
    tokens = command.split()
    script = repo_path(tokens[0])
    assert script.is_file(), f"{command!r} runs a file that does not exist"
    source = script.read_text(encoding="utf-8-sig").lower()
    for token in tokens[1:]:
        found = _PS_FLAG.match(token)
        assert found and found[1].lower() in source, (
            f"{token} is documented but {script.name} has no such parameter"
        )


def test_every_script_the_docs_name_is_in_the_repo():
    for name, text in DOCS.items():
        for mentioned in _SCRIPT_MENTION.findall(text):
            assert (ROOT / "scripts" / mentioned).is_file(), f"{name} names scripts/{mentioned}"


def test_documented_env_names_are_ones_config_reads():
    names = env_names()
    assert names, "the docs carry no .env block"
    for name in names:
        assert f'"{name}"' in CONFIG_SOURCE, f"{name} is documented but config.py never reads it"


# --- documented defaults are the real defaults -------------------------------

@pytest.mark.parametrize(
    "path",
    [
        config.llama_server_path(),
        config.ocr_model_path(),
        config.ocr_mmproj_path(),
        config.ocr_chat_template_path(),
    ],
    ids=["llama-server", "model", "mmproj", "chat template"],
)
def test_operations_documents_the_configured_model_path(path: pathlib.Path):
    assert path.as_posix().replace(str(ROOT.as_posix()), "").lstrip("/") in OPERATIONS


@pytest.mark.parametrize("port", ["APP_PORT", "OCR_PORT", "STRATA_PORT", "UNSLOTH_PORT"])
def test_operations_documents_the_configured_port(port: str, monkeypatch):
    monkeypatch.delenv(port, raising=False)
    value = getattr(config, port.lower())()
    assert str(value) in OPERATIONS
