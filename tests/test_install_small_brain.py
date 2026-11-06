"""T80: the small-brain installer — scripts/install_small_brain.ps1 + its manifest.

Neither file runs here: a test must not download ~3 GB and must not write into
this machine's %LOCALAPPDATA%. What is pinned instead is the deal between the
manifest, the script and app/config.py: every row says what to download, where it
lands and which SHA-256 it must have; the script resolves the same install
directory config resolves (OCR_SMALL_BRAIN_DIR first, %LOCALAPPDATA% only as the
default), keeps every dest inside it, retries the primary CDN once before
falling back to hf-mirror.com, and never promotes a file whose hash was not
checked on the temporary download.
"""
import json
import pathlib
import posixpath
import re

import pytest

from app import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_small_brain.ps1"
MANIFEST = ROOT / "scripts" / "small_brain_manifest.json"

# utf-8-sig: the script carries a BOM so PowerShell 5.1 reads its Turkish text.
script_text = SCRIPT.read_text(encoding="utf-8-sig")
rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
row_by_id = {row["id"]: row for row in rows}

FIELDS = {"id", "url", "dest", "sha256", "size_bytes"}
SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")


def strip_comments(text: str) -> str:
    without_help = re.sub(r"<#.*?#>", "", text, flags=re.S)
    return "\n".join(
        line for line in without_help.splitlines()
        if not line.lstrip().startswith("#")
    )


# Comments stripped once: prose cannot pass as behaviour in any assertion below.
CODE = strip_comments(script_text)


def block(header: str) -> str:
    """A top-level block — a function or the -Check branch — to its closing brace."""
    match = re.search(header, CODE, re.M)
    assert match is not None, f"not in the script: {header}"
    return CODE[match.start(): CODE.index("\n}", match.end())]


def assigned(name: str) -> str:
    match = re.search(rf"^\${name}\s*=\s*(.+?)$", CODE, re.M)
    assert match is not None, f"the script never sets ${name}"
    return match[1].strip()


def relative(path: str) -> str:
    return str(path).replace("\\", "/")


def brain_env(monkeypatch, tmp_path) -> None:
    """A box whose only small-brain setting is a fake %LOCALAPPDATA%."""
    for name in (
        "OCR_SMALL_BRAIN_DIR", "SMALL_BRAIN_SERVER",
        "SMALL_BRAIN_MODEL_FILE", "SMALL_BRAIN_MMPROJ",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_rows_carry_exactly_the_manifest_fields():
    assert len(rows) == len(row_by_id), "row ids must be unique"
    for row in rows:
        assert FIELDS <= set(row) <= FIELDS | {"mirror_url"}, row["id"]
        assert row["url"].startswith("https://"), row["id"]
        assert isinstance(row["size_bytes"], int) and row["size_bytes"] > 0, row["id"]


@pytest.mark.parametrize("row_id", sorted(row_by_id))
def test_every_sha256_is_64_hex(row_id):
    assert SHA256_HEX.match(row_by_id[row_id]["sha256"]), row_id


@pytest.mark.parametrize("row_id", sorted(row_by_id))
def test_every_dest_lands_inside_the_install_dir(row_id):
    dest = relative(row_by_id[row_id]["dest"])
    assert not dest.startswith("/") and ":" not in dest, dest
    assert ".." not in dest.split("/") and not posixpath.normpath(dest).startswith("..")
    # and the script would refuse a row that tried
    guard = block(r"^function Get-DestPath \{")
    assert "IsPathRooted" in guard and '".."' in guard
    assert "GetFullPath" in guard and "StartsWith" in guard


def test_the_script_installs_what_the_launcher_reads(monkeypatch, tmp_path):
    brain_env(monkeypatch, tmp_path)
    expected = {
        relative(path.relative_to(config.small_brain_dir()))
        for path in (
            config.small_brain_server_path(),
            config.small_brain_model_path(),
            config.small_brain_mmproj_path(),
        )
    }
    assert {relative(row["dest"]) for row in rows} == expected
    assert '$ManifestPath = Join-Path $PSScriptRoot "small_brain_manifest.json"' in CODE
    assert "ConvertFrom-Json" in CODE


def test_the_env_override_comes_first_and_localappdata_is_the_default(monkeypatch, tmp_path):
    brain_env(monkeypatch, tmp_path)
    assert config.small_brain_dir() == tmp_path / "ocr-small-brain"
    monkeypatch.setenv("OCR_SMALL_BRAIN_DIR", str(tmp_path / "brain"))
    assert config.small_brain_dir() == tmp_path / "brain"

    getter = block(r"^function Get-InstallDir \{")
    assert "$env:OCR_SMALL_BRAIN_DIR" in getter
    assert getter.index("$env:OCR_SMALL_BRAIN_DIR") < getter.index("$env:LOCALAPPDATA")
    assert '"ocr-small-brain"' in getter
    assert "$InstallDir = Get-InstallDir" in CODE


def test_the_rows_are_the_cpu_build_and_the_two_model_files():
    llama = row_by_id["llama-cpp-b12177-cpu"]
    assert "b12177" in llama["url"] and "cpu" in llama["url"]
    assert llama["url"].endswith(".zip") and relative(llama["dest"]) == "llama/llama-server.exe"
    assert "Qwen3-VL-4B" in row_by_id["qwen3-vl-4b-iq4-xs"]["url"]
    assert "IQ4_XS" in row_by_id["qwen3-vl-4b-iq4-xs"]["url"]
    assert row_by_id["qwen3-vl-4b-mmproj-f16"]["url"].endswith("/mmproj-F16.gguf")


def test_the_hf_rows_carry_the_mirror_and_the_github_row_does_not():
    for row in rows:
        name = row["url"].rsplit("/", 1)[-1]
        if "huggingface.co" in row["url"]:
            assert row["mirror_url"].startswith("https://hf-mirror.com/"), row["id"]
            assert row["mirror_url"].rsplit("/", 1)[-1] == name, row["id"]
        else:  # a missing mirror_url means primary CDN only
            assert "mirror_url" not in row, row["id"]


def test_the_primary_cdn_is_retried_once_then_the_mirror_is_used():
    assert assigned("PrimaryAttempts") == "2"
    assert "hf-mirror.com" in assigned("MirrorHost")
    retry = block(r"^function Receive-Row \{")
    assert re.search(r"for \(\$attempt = 1; \$attempt -le \$PrimaryAttempts", retry)
    assert retry.index("Invoke-DownloadTry -Url $Row.url") < retry.index(
        "Invoke-DownloadTry -Url $Row.mirror_url"
    )
    # a row without a mirror says so instead of quietly giving up
    assert "exit 1" in retry


def test_the_hash_is_verified_on_the_temp_file_before_anything_is_moved():
    verify = block(r"^function Test-DownloadedRow \{")
    assert "Get-FileHash -LiteralPath $PartFile -Algorithm SHA256" in verify
    after_hash = verify[verify.index("Get-FileHash"):]
    assert "Remove-Item -LiteralPath $PartFile" in after_hash, "bad file must be dropped"
    assert "exit 1" in after_hash

    install = block(r"^function Install-Row \{")
    temp = '$partFile = "$dest.part"'
    checked = "Test-DownloadedRow -Row $Row -PartFile $partFile"
    assert temp in install
    assert install.index(temp) < install.index(checked), "hash the file the download wrote"
    assert install.index(checked) < install.index(
        "Move-Item -LiteralPath $partFile -Destination $dest"
    )
    assert install.index(checked) < install.index("Expand-Archive")


def test_the_verified_archive_is_unpacked_into_llama_server_exe():
    install = block(r"^function Install-Row \{")
    assert "Expand-Archive -LiteralPath $partFile -DestinationPath $parent -Force" in install
    assert "llama-server.exe" in install


def test_check_reports_installed_and_missing_and_always_exits_zero():
    assert "[switch]$Check" in script_text and "[switch]$Force" in script_text
    check = block(r"^if \(\$Check\) \{")
    assert "Test-Path -LiteralPath $dest -PathType Leaf" in check
    assert "$missing" in check and "durum:" in check
    assert check.count("exit") == 1 and check.rstrip().endswith("exit 0")
    # only -Force re-downloads what is already in place
    assert "if (-not $Force -and (Test-Path" in block(r"^function Install-Row \{")


def test_it_prints_what_it_installed():
    code = CODE
    assert 'Write-Host "kurulum dizini: $InstallDir"' in code
    summary = code[code.index('Write-Host "kurulan küçük beyin:"'):]
    assert "foreach ($entry in $installed)" in summary
    for value in ("$entry.Id", "$file.Length / 1MB", "$file.FullName"):
        assert value in summary
