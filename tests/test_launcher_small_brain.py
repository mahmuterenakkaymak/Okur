"""T78: the launcher's red lines about the small brain, and nothing on fire.

Two boxes where the small brain cannot start: one where
scripts\\install_small_brain.ps1 never ran, and one where somebody else already
listens on the port. Each is a single red ✗ line that names the fix — and the
stack still comes up: the app is spawned, waited on and reported as served, and
only the roll-call's success is withheld. Children, the health gate and the
final wait are faked at the seams tests/test_run_py.py uses; the pre-flight, the
pid bookkeeping and the printing are the real thing.
"""
import os
import socket
import webbrowser

import pytest

import run
from app import config

INSTALL_COMMAND = "scripts\\install_small_brain.ps1"
ADMIN_URL = "http://127.0.0.1:8090/admin"

OWN_PREFIXES = (
    "APP_", "OCR_", "STRATA_", "UNSLOTH_", "LLAMA_", "PROBE_",
    "STARTUP_", "DATA_DIR", "DB_PATH",
    "SMALL_BRAIN_", "STRUCTURER_BACKEND",
)


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    for name in [n for n in os.environ if n.startswith(OWN_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # a CPU-only box that has never run the installer: stage 2 is the small
    # brain, and its directory is this one — empty.
    monkeypatch.setenv("OCR_SMALL_BRAIN_DIR", str(tmp_path / "ocr-small-brain"))
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")


def install_brain() -> None:
    """The three files the installer leaves behind."""
    for target in (
        config.small_brain_server_path(),
        config.small_brain_model_path(),
        config.small_brain_mmproj_path(),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def checks(text: str) -> list[str]:
    return [line for line in lines(text) if "✓" in line]


def label(check_line: str) -> str:
    return check_line.split("  ")[0]


def brain_line(text: str) -> str:
    """The roll-call line the small brain owns."""
    return next(line for line in lines(text) if line.startswith("Small brain"))


class FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None


class FakeWorker:
    started = stopped = 0

    def __init__(self, db_path=None, **kwargs):
        pass

    def start(self):
        FakeWorker.started += 1

    def stop(self, timeout: float = 10.0):
        FakeWorker.stopped += 1


@pytest.fixture
def launcher(monkeypatch):
    """start() with the children, the health gate and the wait faked out."""
    FakeWorker.started = FakeWorker.stopped = 0
    state = {"spawned": [], "killed": [], "opened": []}

    def fake_spawn(name, args):
        child = FakeChild(987_000 + len(state["spawned"]))
        state["spawned"].append((name, args, child))
        return child

    monkeypatch.setattr(run, "_spawn", fake_spawn)
    monkeypatch.setattr(run, "wait_healthy", lambda *a, **k: True)
    monkeypatch.setattr(
        run, "_terminate", lambda pid, grace=0.0: state["killed"].append(pid) or True
    )
    monkeypatch.setattr(run, "QueueWorker", FakeWorker)
    monkeypatch.setattr(run, "_wait_for_children", lambda children: None)
    monkeypatch.setattr(webbrowser, "open", state["opened"].append)
    return state


@pytest.fixture
def busy_port():
    """A port with a real listener on it — what the bind-probe must refuse."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    yield holder.getsockname()[1]
    holder.close()


@pytest.fixture
def free_port():
    """A port nothing listens on, released so the launcher may take it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# --- the box where the installer never ran -----------------------------------


def test_a_missing_install_skips_the_spawn_and_names_the_installer(launcher, capsys):
    assert run.start(8081, 8090, browser=False) == 1
    out = capsys.readouterr().out

    assert {name for name, _, _ in launcher["spawned"]} == {"ocr", "app"}
    line = brain_line(out)
    assert "✗" in line and "model dosyaları yok" in line
    assert INSTALL_COMMAND in out
    assert str(config.small_brain_dir()) in out
    assert "Traceback" not in out


def test_a_brain_missing_only_its_mmproj_is_still_not_spawned(launcher, capsys):
    install_brain()
    config.small_brain_mmproj_path().unlink()

    assert run.start(8081, 8090, browser=False) == 1
    out = capsys.readouterr().out
    assert "model dosyaları yok" in brain_line(out)
    assert "dolu" not in out  # the port is not the complaint here
    assert {name for name, _, _ in launcher["spawned"]} == {"ocr", "app"}


def test_the_app_is_still_spawned_waited_on_and_served(launcher, capsys):
    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out

    assert [name for name, _, _ in launcher["spawned"]] == ["app", "ocr"]
    assert [label(line) for line in checks(out)] == ["OCR", "Uygulama"]
    assert ADMIN_URL in out
    assert launcher["opened"] == [ADMIN_URL]


def test_the_roll_call_never_gives_a_brain_it_skipped_a_check(launcher, capsys):
    assert run.start(8081, 8090, browser=False) == 1
    out = capsys.readouterr().out

    assert "✓" not in brain_line(out)
    assert [label(line) for line in checks(out)] == ["OCR", "Uygulama"]


def test_missing_files_are_named_before_a_busy_port(launcher, busy_port, monkeypatch, capsys):
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{busy_port}")

    assert run.start(8081, 8090, browser=False) == 1
    assert "model dosyaları yok" in brain_line(capsys.readouterr().out)


def test_a_skipped_spawn_leaves_no_pid_for_stop_to_kill(launcher, capsys):
    stale = run.pid_path("small-brain")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("424242", encoding="utf-8")

    assert run.start(8081, 8090, browser=False) == 1
    assert stale.exists() is False
    assert 424_242 not in launcher["killed"]
    assert "424242" not in capsys.readouterr().out


# --- the box where the port is already taken ---------------------------------


def test_a_busy_port_is_named_before_anything_is_spawned(
    launcher, busy_port, monkeypatch, capsys
):
    monkeypatch.setattr(config, "small_brain_ready", lambda: True)
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{busy_port}")
    monkeypatch.setattr(run, "_listener_pids", lambda port: [4321])
    monkeypatch.setattr(run, "_process_name", lambda pid: "llama-server.exe")

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out

    line = brain_line(out)
    assert "✗" in line and f"port {busy_port} dolu" in line
    assert "pid 4321 (llama-server.exe)" in out
    assert "python run.py --stop" in out
    assert {name for name, _, _ in launcher["spawned"]} == {"ocr", "app"}
    assert [label(line) for line in checks(out)] == ["OCR", "Uygulama"]
    assert launcher["opened"] == [ADMIN_URL]
    assert "Traceback" not in out


def test_a_holder_lookup_that_fails_is_still_a_line_not_a_traceback(
    launcher, busy_port, monkeypatch, capsys
):
    monkeypatch.setattr(config, "small_brain_ready", lambda: True)
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{busy_port}")

    def no_tools(*args, **kwargs):
        raise OSError("bu kutuda netstat yok")

    monkeypatch.setattr(run.subprocess, "run", no_tools)

    assert run.start(8081, 8090, browser=False) == 1
    out = capsys.readouterr().out
    assert f"port {busy_port} dolu" in brain_line(out)
    assert "bilinmeyen bir süreç" in out
    assert "python run.py --stop" in out
    assert [label(line) for line in checks(out)] == ["OCR", "Uygulama"]
    assert "Traceback" not in out


def test_the_busy_port_line_names_the_real_holder_when_the_os_will_say(busy_port):
    if not run._listener_pids(busy_port):
        pytest.skip("this OS's netstat/lsof will not name the listener")
    assert str(os.getpid()) in run._port_holder(busy_port)


def test_the_bind_probe_notices_a_listener_and_lets_a_free_port_go(busy_port, free_port):
    assert run._port_free("127.0.0.1", busy_port) is False
    assert run._port_free("127.0.0.1", free_port) is True


def test_the_port_is_probed_before_the_small_brain_is_spawned(
    launcher, monkeypatch, free_port, capsys
):
    install_brain()
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{free_port}")
    order: list[str] = []
    real_spawn = run._spawn

    def probe(name, args):
        order.append(f"spawn:{name}")
        return real_spawn(name, args)

    monkeypatch.setattr(run, "_spawn", probe)
    monkeypatch.setattr(
        run, "small_brain_block", lambda: order.append("block") or None
    )

    assert run.start(8081, 8090, browser=False) == 0
    assert order.index("block") < order.index("spawn:small-brain")


def test_an_installed_brain_on_a_free_port_is_still_a_green_child(
    launcher, monkeypatch, free_port, capsys
):
    install_brain()
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{free_port}")

    assert run.start(8081, 8090, browser=False) == 0
    out = capsys.readouterr().out

    assert {name for name, _, _ in launcher["spawned"]} == {"app", "ocr", "small-brain"}
    assert [label(line) for line in checks(out)] == ["OCR", "Small brain", "Uygulama"]
    assert run.pid_path("small-brain").exists() is False
    assert "install_small_brain" not in out
