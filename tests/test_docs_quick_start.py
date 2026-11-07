"""T106: HIZLI-BASLANGIC.md — the Turkish quick start, pinned to the code it describes.

tests/test_docs.py holds README.md and OPERATIONS.md to the code; the file the
operator on the box actually reads was left out, which is how it ended up
ordering a Strata-only box. Same rule here: the stage-2 default it quotes is the
one app/config.py uses, every env name it quotes has a getter there, every script
and flag it names exists, every port and count is what config, run.py and the
suite print today, and the default backend never has Strata as a prerequisite.
"""
from __future__ import annotations

import importlib.util
import inspect
import pathlib
import re
import subprocess
import sys

import pytest

import run as launcher
from app import config
from scripts import acceptance, live_ocr_gate, small_brain_gate

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = (ROOT / "HIZLI-BASLANGIC.md").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
LAUNCHER_SOURCE = inspect.getsource(launcher)

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)
_TRAILING_COMMENT = re.compile(r"\s+#.*$")
_ENV_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.M)
_BACKTICKED_ENV = re.compile(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`")
_SCRIPT_MENTION = re.compile(r"[\w./\\-]+\.(?:py|ps1|md)")
# ASSUMPTION: the doc states its backend default in the words
# "`STRUCTURER_BACKEND` varsayılan olarak `x`", so this reads the sentence out
# instead of guessing which bare "small" or "strata" in a paragraph was the default.
_BACKEND_DEFAULT = re.compile(r"`STRUCTURER_BACKEND` varsayılan olarak `(\w+)`")


def section(prefix: str, level: int = 2) -> str:
    """One section's body, from its heading to the next heading of that level."""
    mark = "#" * level + " "
    body, inside, found = [], False, False
    for line in DOC.splitlines():
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
    relative = re.sub(r"^\.[/\\]", "", token.replace("\\", "/"))
    return ROOT / relative


def python_commands() -> list[str]:
    return [line for line in code_lines(DOC) if "python" in line.split()[0].lower()]


def powershell_commands() -> list[str]:
    return [line for line in code_lines(DOC) if line.split()[0].lower().endswith(".ps1")]


def env_blocks() -> list[str]:
    return [block for lang, block in _FENCE.findall(DOC) if lang == "env"]


def config_getters() -> dict[str, str]:
    """env name -> the config function whose body reads it."""
    getters: dict[str, str] = {}
    current = ""
    for line in CONFIG_SOURCE.splitlines():
        if line.startswith("def "):
            current = line[len("def "):].partition("(")[0]
        if current:
            for name in re.findall(r'"([A-Z][A-Z0-9_]*)"', line):
                getters.setdefault(name, current)
    return getters


@pytest.fixture(scope="module")
def collected() -> int:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    found = re.findall(r"(\d+) tests collected", out)
    assert found, f"the suite did not collect: {out[-400:]}"
    return int(found[-1])


# --- required sections -------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    ["5 dakikada dene", "Gerçek hatla çalıştır", "Telefona PWA kur",
     "Kontrol listesi", "Sorun çıkarsa"],
)
def test_quick_start_has_every_required_section(title: str):
    mark = "## "
    headings = [line[len(mark):].strip() for line in DOC.splitlines() if line.startswith(mark)]
    assert any(h.lower().startswith(title.lower()) for h in headings)


def test_quick_start_hands_the_operator_to_the_other_docs():
    for detail in ["README.md", "CONTRACT.md", "OPERATIONS.md"]:
        assert detail in DOC


# --- the cutover: small brain first, Strata is the upgrade -------------------

def test_the_backend_default_it_quotes_is_configs_default(monkeypatch):
    monkeypatch.delenv("STRUCTURER_BACKEND", raising=False)
    quoted = _BACKEND_DEFAULT.findall(section("Gerçek hatla"))
    assert quoted == [config.structurer_backend()], f"the quick start quotes {quoted}"


def test_the_cpu_brain_is_what_the_real_run_section_installs_first(monkeypatch):
    monkeypatch.delenv("STRUCTURER_BACKEND", raising=False)
    monkeypatch.delenv("SMALL_BRAIN_BASE_URL", raising=False)
    body = section("Gerçek hatla")
    install, start = body.index("install_small_brain.ps1"), body.index("run.py")
    assert install < start, "the brain is installed before the first python run.py"
    for detail in [
        "scripts\\install_small_brain.ps1",
        f"http://127.0.0.1:{config.small_brain_port()}/v1/models",
        "install_small_brain.ps1 -Check",
        "OPERATIONS.md",
    ]:
        assert detail in body


def test_strata_is_never_a_prerequisite_of_the_default_backend():
    body = section("Gerçek hatla")
    assert "Ön koşul" not in body, "nothing is a prerequisite of the default backend"
    lines = body.splitlines()
    first = next(i for i, line in enumerate(lines) if "strata" in line.lower())
    assert "STRUCTURER_BACKEND" in lines[first], (
        "the first Strata mention must be the switch that offers it, not a demand"
    )


def test_the_roll_call_it_promises_is_the_one_the_launcher_prints(monkeypatch):
    monkeypatch.delenv("STRUCTURER_BACKEND", raising=False)
    names = [name for name, _, _ in launcher.roll_call()]
    assert names == ["ocr", "small-brain", "app"]
    body = section("Gerçek hatla")
    for label in (launcher.LABELS[name] for name in names):
        assert label in body, f"the quick start never waits for {label}"


def test_the_missing_brain_line_names_the_command_that_fixes_it():
    body = section("Gerçek hatla")
    for detail in [
        "Small brain ✗ model dosyaları yok",
        launcher.INSTALL_SCRIPT,
        "run.py --stop",
    ]:
        assert detail in body
    assert '"model dosyaları yok"' in LAUNCHER_SOURCE
    assert 'f"port {port} dolu"' in LAUNCHER_SOURCE


def test_the_busy_brain_port_line_names_the_configured_port(monkeypatch):
    monkeypatch.delenv("SMALL_BRAIN_BASE_URL", raising=False)
    body = section("Sorun çıkarsa")
    for detail in [
        f"Small brain ✗ port {config.small_brain_port()} dolu",
        "install_small_brain.ps1",
        "OCR_SMALL_BRAIN_DIR",
        "SMALL_BRAIN_BASE_URL",
        "run.py --stop",
    ]:
        assert detail in body


# --- names the code really has ----------------------------------------------

def test_every_backticked_env_name_has_a_config_getter():
    names = set(_BACKTICKED_ENV.findall(DOC))
    assert names, "the quick start quotes no env name"
    getters = config_getters()
    unknown = sorted(name for name in names if name not in getters)
    assert not unknown, f"app/config.py reads none of {unknown}"


def test_every_env_name_in_its_env_block_has_a_config_getter():
    blocks = env_blocks()
    assert blocks, "the quick start has no .env block"
    getters = config_getters()
    for block in blocks:
        for name in _ENV_ASSIGN.findall(block):
            assert name in getters, f"{name} is documented but no config getter reads it"


def test_every_script_the_quick_start_names_is_in_the_repo():
    for mentioned in _SCRIPT_MENTION.findall(DOC):
        assert repo_path(mentioned).is_file(), f"HIZLI-BASLANGIC.md names {mentioned}"


@pytest.mark.parametrize("command", python_commands(), ids=lambda c: c[:58])
def test_documented_python_command_and_its_flags_exist(command: str):
    tokens = command.split()
    if tokens[1] == "-m":
        assert importlib.util.find_spec(tokens[2]), f"{tokens[2]} is not importable"
        return
    script = repo_path(tokens[1])
    assert script.is_file(), f"{command!r} runs a file that does not exist"
    source = script.read_text(encoding="utf-8")
    for flag in (t for t in tokens[2:] if t.startswith("--")):
        assert f'"{flag}"' in source, f"{flag} is documented but {script.name} never parses it"


@pytest.mark.parametrize("command", powershell_commands(), ids=lambda c: c[:58])
def test_documented_powershell_command_and_its_parameters_exist(command: str):
    tokens = command.split()
    script = repo_path(tokens[0])
    assert script.is_file(), f"{command!r} runs a file that does not exist"
    source = script.read_text(encoding="utf-8-sig").lower()
    for token in tokens[1:]:
        found = re.match(r"^-(\w+)$", token)
        assert found and found[1].lower() in source, (
            f"{token} is documented but {script.name} has no such parameter"
        )


@pytest.mark.parametrize(
    "flag, getter",
    [("--app-port", config.app_port), ("--ocr-port", config.ocr_port)],
    ids=["app-port", "ocr-port"],
)
def test_documented_port_flags_default_to_the_configured_ports(flag, getter, monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.delenv("OCR_PORT", raising=False)
    for value in re.findall(rf"{flag} (\d+)", DOC):
        assert int(value) == getter(), f"{flag} {value} is not this box's default"


def test_the_stage2_port_it_names_is_configs_small_brain_port(monkeypatch):
    monkeypatch.delenv("SMALL_BRAIN_BASE_URL", raising=False)
    ports = set(re.findall(r"http://127\.0\.0\.1:(\d+)/v1/models", DOC))
    assert ports == {str(config.small_brain_port())}


def test_the_app_urls_it_names_are_on_the_configured_app_port(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    ports = set(re.findall(r"http://localhost:(\d+)/", DOC))
    assert ports == {str(config.app_port())}


# --- counts, from the scripts and the suite that print them ------------------

def test_the_gate_and_acceptance_counts_are_the_scripts():
    assert f"{len(acceptance.CHECKS)} kabul kontrolü" in DOC
    schema, valid = small_brain_gate.NEED_SCHEMA, small_brain_gate.NEED_VALID
    assert f"{schema} fixture, {schema}/{schema} şema, {valid}/{schema} doğrulayıcı" in DOC
    assert f"{len(live_ocr_gate.FIXTURES)} gerçek fiş" in DOC


def test_both_real_receipt_gates_have_their_own_line():
    lines = section("Kontrol listesi").splitlines()
    for gate in ["small_brain_gate.py", "live_ocr_gate.py"]:
        named = [line for line in lines if gate in line]
        assert len(named) == 1, f"{gate} is documented on {len(named)} lines, want 1"
        assert named[0].strip().startswith(".venv"), f"{gate} is not documented as a command"


def test_the_suite_count_it_prints_is_the_count_the_suite_prints(collected):
    stated = [int(n) for n in re.findall(r"≈(\d+) test", DOC)]
    assert stated, "the quick start stopped saying how big the suite is"
    # ASSUMPTION: the suite grows by a few tests every task, so this fails on a
    # stale era (679 next to 964) rather than on the next added test.
    tolerance = max(10, collected // 20)
    for value in stated:
        assert abs(value - collected) <= tolerance, (
            f"HIZLI-BASLANGIC.md says ≈{value} tests; pytest collects {collected}"
        )


# --- what this task must not touch ------------------------------------------

def test_the_pwa_and_tailscale_copy_survives():
    body = section("Telefona PWA")
    for detail in [
        "scripts\\tailscale_serve.ps1",
        ".ts.net",
        "/app",
        "API anahtarı",
        "Ana Ekrana Ekle",
        "keys_cli revoke",
    ]:
        assert detail in body
