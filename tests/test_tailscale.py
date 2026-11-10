"""T47: scripts/tailscale_serve.ps1 and the README section that documents it.

The .ps1 is parsed, never run — a test must not touch this machine's tailnet
state. The README is then checked against what the parse found, so the port, the
certificate path and the rollback command cannot drift apart from the script.
"""
import pathlib
import re

import pytest

from app import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tailscale_serve.ps1"
README = ROOT / "docs" / "REFERENCE.md"  # the manual that documents the script

# utf-8-sig: the script carries a BOM so PowerShell 5.1 reads its Turkish text.
script_text = SCRIPT.read_text(encoding="utf-8-sig")
readme = README.read_text(encoding="utf-8")

_DEFAULT = re.compile(r'\$(\w+)\s*\]?\s*=\s*(?:"([^"]*)"|(\d+))')
_ARGS = re.compile(r'-Arguments\s+@\(([^)]*)\)')
_STRING = re.compile(r'"([^"]*)"')


def param_defaults() -> dict[str, str]:
    block = script_text[script_text.index("param("):]
    block = block[: block.index("\n)")]
    return {m[0]: (m[1] or m[2]) for m in _DEFAULT.findall(block)}


def tailscale_commands() -> list[list[str]]:
    """Every tailscale invocation the script can reach, variables expanded."""
    defaults = param_defaults()
    commands = []
    for group in _ARGS.findall(script_text):
        args = [
            re.sub(r"\$(\w+)", lambda m: defaults.get(m[1], m[0]), arg)
            for arg in _STRING.findall(group)
        ]
        commands.append(["tailscale", *args])
    return commands


def code_only() -> str:
    """The script without its comment-based help, so prose cannot pass as code."""
    without_help = re.sub(r"<#.*?#>", "", script_text, flags=re.S)
    return "\n".join(
        line for line in without_help.splitlines()
        if not line.lstrip().startswith("#")
    )


def command_starting_with(*prefix: str) -> list[str]:
    for command in tailscale_commands():
        if command[1:1 + len(prefix)] == list(prefix):
            return command
    raise AssertionError(f"no tailscale {' '.join(prefix)} command in the script")


def test_defaults_are_the_app_port_and_the_gitignored_cert_dir(monkeypatch):
    monkeypatch.delenv("APP_PORT", raising=False)
    defaults = param_defaults()
    assert defaults["AppPort"] == str(config.app_port())
    assert defaults["HttpsPort"] == "443"
    # data/ is gitignored, so the exported private key can never be committed.
    assert defaults["CertDir"] == "data\\certs"


def test_https_is_enabled_on_the_app_port():
    serve = command_starting_with("serve", "--bg")
    assert "--https=443" in serve
    assert "http://127.0.0.1:8090" in serve


def test_the_certificate_is_written_under_the_cert_dir():
    cert = command_starting_with("cert")
    assert "--cert-file" in cert and "--key-file" in cert
    for name in ("certFile", "keyFile"):
        assert re.search(rf"\${name}\s*=\s*Join-Path\s+\$CertDir\b", script_text)


def test_rollback_takes_https_down_and_is_what_the_flag_runs():
    rollback = re.search(r'^\$RollbackCommand\s*=\s*"([^"]*)"', script_text, re.M)
    assert rollback is not None
    assert rollback[1] == "tailscale serve --https=$HttpsPort off"
    assert command_starting_with("serve", "--https=443", "off") == [
        "tailscale", "serve", "--https=443", "off"
    ]


def test_the_script_never_reaches_for_the_public_internet():
    # funnel is the command that would publish the app to the whole internet;
    # naming it in the help block is documentation, running it is not.
    assert "funnel" in script_text
    assert "funnel" not in code_only()
    assert not any("funnel" in command for command in tailscale_commands())


def test_readme_names_the_port_the_script_proxies():
    assert param_defaults()["AppPort"] in readme


def test_readme_names_the_cert_path_and_calls_it_a_secret():
    assert param_defaults()["CertDir"] in readme
    section = readme[readme.index("## Tailscale"):]
    assert "gitignored" in section and "secret" in section


def test_readme_names_the_rollback_command_the_script_prints():
    rollback = re.search(r'^\$RollbackCommand\s*=\s*"([^"]*)"', script_text, re.M)[1]
    assert rollback.replace("$HttpsPort", param_defaults()["HttpsPort"]) in readme


def test_readme_keeps_the_no_public_internet_rule():
    section = readme[readme.index("### No public internet"):]
    assert "funnel" in section
    assert "tailscale funnel" in section


@pytest.mark.parametrize("detail", ["App Store", "/app", "Anahtarlar", "Revoke"])
def test_readme_enrolls_a_worker_phone(detail: str):
    section = readme[readme.index("### Enrolling a worker"):]
    assert detail in section
