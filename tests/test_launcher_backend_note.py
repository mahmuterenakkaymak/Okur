"""T95: on a Strata box the small brain is a note, never a requirement.

Two lines used to fail the start whatever stage 2 was configured to use: the
pre-flight that answers "model dosyaları yok" on a box that never ran the
installer, and a spawned brain that never turns healthy (llama-server exits on
a model-load error, and the shared STARTUP_WAIT_S has to cover OCR's cold load
too). Both still print their ✗ and their help line — but only
STRUCTURER_BACKEND=small makes them fatal: the app is still waited on and
reported, the admin URL still opens and the exit code is 0. A
SMALL_BRAIN_BASE_URL whose host is not this machine is never spawned locally;
it is waited for like Strata, and its ✗ names the endpoint instead of a log
that stays empty. Children, the health gate and the final wait are faked at the
seams tests/test_run_py.py uses; the pre-flight, the roll-call, the pid
bookkeeping and the exit code are the real thing.
"""
import os
import socket
import webbrowser

import pytest

import run
from app import config

INSTALL_COMMAND = "scripts\\install_small_brain.ps1"
ADMIN_URL = "http://127.0.0.1:8090/admin"
# another machine on the tailnet: the brain runs (and is started) there
REMOTE_URL = "http://192.168.50.40:8100"

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
    # today's documented box: Strata runs stage 2 and the installer never ran.
    # Since M8 the default is the small brain, so the box this file is about is
    # pinned here; the tests that describe the brain as stage 2 set it themselves.
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    monkeypatch.setenv("OCR_SMALL_BRAIN_DIR", str(tmp_path / "ocr-small-brain"))


def install_brain() -> None:
    """The three files the installer leaves behind."""
    for target in (
        config.small_brain_server_path(),
        config.small_brain_model_path(),
        config.small_brain_mmproj_path(),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")


@pytest.fixture
def free_port():
    """A port nothing listens on, released so the launcher may take it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def local_brain(monkeypatch, free_port):
    """An installed brain on a free local port: nothing blocks its spawn."""
    install_brain()
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", f"http://127.0.0.1:{free_port}")
    return config.small_brain_base_url()


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def checks(text: str) -> list[str]:
    return [line for line in lines(text) if "✓" in line]


def label(check_line: str) -> str:
    return check_line.split("  ")[0]


def brain_line(text: str) -> str:
    """The roll-call line the small brain was judged on, not its spawn line."""
    return next(
        line
        for line in lines(text)
        if line.startswith("Small brain") and ("✗" in line or "✓" in line)
    )


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
    """start() with the children, the health gate and the wait faked out; add a
    base_url to ``down`` to make the service that never heals."""
    FakeWorker.started = FakeWorker.stopped = 0
    state = {"down": set(), "spawned": [], "killed": [], "opened": []}

    def fake_spawn(name, args):
        child = FakeChild(987_000 + len(state["spawned"]))
        state["spawned"].append((name, args, child))
        return child

    def fake_wait_healthy(base_url, timeout, path=run.HEALTH_PATH, **kwargs):
        return base_url not in state["down"]

    monkeypatch.setattr(run, "_spawn", fake_spawn)
    monkeypatch.setattr(run, "wait_healthy", fake_wait_healthy)
    monkeypatch.setattr(
        run, "_terminate", lambda pid, grace=0.0: state["killed"].append(pid) or True
    )
    monkeypatch.setattr(run, "QueueWorker", FakeWorker)
    monkeypatch.setattr(run, "_wait_for_children", lambda children: None)
    monkeypatch.setattr(webbrowser, "open", state["opened"].append)
    return state


def spawned_names(launcher) -> set[str]:
    return {name for name, _, _ in launcher["spawned"]}


# --- the documented box: Strata stage 2, brain never installed ---------------


def test_the_note_box_starts_serves_and_exits_zero(launcher, capsys):
    assert config.structurer_backend() == "strata"

    assert run.start(8081, 8090, browser=True) == 0
    out = capsys.readouterr().out

    assert spawned_names(launcher) == {"ocr", "app"}
    assert [label(line) for line in checks(out)] == ["OCR", "Strata", "Uygulama"]
    assert ADMIN_URL in out
    assert launcher["opened"] == [ADMIN_URL]
    assert "Traceback" not in out


def test_the_note_still_prints_its_own_red_line_and_the_installer(launcher, capsys):
    assert run.start(8081, 8090, browser=False) == 0
    out = capsys.readouterr().out

    line = brain_line(out)
    assert "✗" in line and "model dosyaları yok" in line
    assert INSTALL_COMMAND in out
    assert str(config.small_brain_dir()) in out
    assert "✓" not in line


def test_a_skipped_spawn_still_leaves_no_pid_for_stop_to_kill(launcher):
    stale = run.pid_path("small-brain")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("424242", encoding="utf-8")

    assert run.start(8081, 8090, browser=False) == 0
    assert stale.exists() is False
    assert 424_242 not in launcher["killed"]


# --- a spawned brain that never turns healthy --------------------------------


def test_a_brain_that_never_heals_is_a_note_while_strata_runs_stage_2(
    launcher, local_brain, capsys
):
    launcher["down"].add(local_brain)

    assert run.start(8081, 8090, browser=True) == 0
    out = capsys.readouterr().out

    assert "✗" in brain_line(out)
    assert str(run.log_path("small-brain")) in out
    assert "python run.py" in out
    assert [label(line) for line in checks(out)] == ["OCR", "Strata", "Uygulama"]
    assert launcher["opened"] == [ADMIN_URL]
    assert spawned_names(launcher) == {"ocr", "app", "small-brain"}
    # the stack came up and only went down with the launcher, not on the ✗
    assert sorted(launcher["killed"]) == sorted(child.pid for _, _, child in launcher["spawned"])


def test_the_same_brain_fails_the_start_when_it_runs_stage_2(launcher, monkeypatch, local_brain, capsys):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    launcher["down"].add(local_brain)

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out

    assert "✗" in brain_line(out)
    assert str(run.log_path("small-brain")) in out
    assert launcher["opened"] == []


def test_a_missing_install_still_fails_the_start_when_the_brain_is_stage_2(
    launcher, monkeypatch, capsys
):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")

    assert run.start(8081, 8090, browser=True) == 1
    assert "model dosyaları yok" in brain_line(capsys.readouterr().out)


# --- a base url that names another machine -----------------------------------


def test_only_a_brain_on_this_box_is_ours_to_spawn(monkeypatch):
    for url, local in (
        ("http://127.0.0.1:8100", True),
        ("http://localhost:8100", True),
        ("http://[::1]:8100", True),
        (f"http://{socket.gethostname()}:8100", True),
        (REMOTE_URL, False),
    ):
        monkeypatch.setenv("SMALL_BRAIN_BASE_URL", url)
        assert run.small_brain_is_local() is local, url


def test_a_remote_brain_is_never_spawned_or_preflighted_locally(launcher, monkeypatch, capsys):
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", REMOTE_URL)

    assert run.start(8081, 8090, browser=True) == 0
    out = capsys.readouterr().out

    assert "small-brain" not in spawned_names(launcher)
    assert not run.pid_path("small-brain").exists()
    assert "model dosyaları yok" not in out
    assert f"bekleniyor… ({REMOTE_URL})" in out
    assert [label(line) for line in checks(out)] == [
        "OCR",
        "Strata",
        "Small brain",
        "Uygulama",
    ]
    assert launcher["opened"] == [ADMIN_URL]


def test_a_dead_remote_brain_names_the_endpoint_and_not_a_local_log(
    launcher, monkeypatch, capsys
):
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", REMOTE_URL)
    launcher["down"].add(REMOTE_URL)

    assert run.start(8081, 8090, browser=True) == 0
    out = capsys.readouterr().out

    assert "✗" in brain_line(out)
    assert REMOTE_URL in out
    assert str(run.log_path("small-brain")) not in out
    assert launcher["opened"] == [ADMIN_URL]


def test_a_remote_brain_is_still_stage_2_when_the_backend_says_small(
    launcher, monkeypatch, capsys
):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", REMOTE_URL)
    launcher["down"].add(REMOTE_URL)

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out

    assert "✗" in brain_line(out)
    assert REMOTE_URL in out
    assert launcher["opened"] == []
