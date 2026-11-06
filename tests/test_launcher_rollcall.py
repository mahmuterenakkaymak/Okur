"""D7: the launcher's roll-call.

One green ✓ line per service as it turns healthy, in the order PLAN names
(OCR, Strata, Small brain, Uygulama), the admin UI only once all of them are up,
and a ✗ that names the log to read (or, for Strata, the process to start) plus
the retry command. Children, health gate, worker and browser stay faked at the
same seams tests/test_run_py.py uses; the roll-call itself is the real code.
"""
import os
import sys
import webbrowser

import pytest

import run
from app import config, status

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


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def checks(text: str) -> list[str]:
    return [line for line in lines(text) if "✓" in line]


def label(check_line: str) -> str:
    """The service a ✓ line belongs to, before _say's column padding."""
    return check_line.split("  ")[0]


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
    """start() with the outside world faked; add a base_url to ``down`` to make
    the service that never heals."""
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


# --- what is waited for, and where ---


def test_roll_call_reads_ocr_strata_small_brain_then_the_app_there(monkeypatch):
    monkeypatch.setenv("OCR_PORT", "9101")
    monkeypatch.setenv("APP_PORT", "9100")
    assert run.roll_call() == [
        ("ocr", "http://127.0.0.1:9101", run.HEALTH_PATH),
        ("strata", "http://127.0.0.1:8080", status.PROBE_PATH),
        ("small-brain", "http://127.0.0.1:8100", status.PROBE_PATH),
        ("app", "http://127.0.0.1:9100", run.HEALTH_PATH),
    ]


def test_the_small_brain_is_waited_for_whatever_stage_two_is_named(monkeypatch):
    for backend in ("small", "strata"):
        monkeypatch.setenv("STRUCTURER_BACKEND", backend)
        assert ("small-brain", "http://127.0.0.1:8100", status.PROBE_PATH) in run.roll_call()


def test_strata_is_only_waited_for_when_it_is_the_stage_two_backend(monkeypatch):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    assert [name for name, _, _ in run.roll_call()] == ["ocr", "small-brain", "app"]


def test_stop_never_touches_strata_that_this_launcher_never_started(launcher, capsys):
    assert run.start(8081, 8090, browser=False) == 0
    capsys.readouterr()
    assert "strata" not in run.SERVICES
    assert run.stop() == 0
    assert "Strata" not in capsys.readouterr().out


# --- the green lines ---


def test_every_healthy_service_gets_its_own_check_line_in_order(launcher, capsys):
    assert run.start(8081, 8090, browser=True) == 0
    assert [label(line) for line in checks(capsys.readouterr().out)] == [
        "OCR",
        "Strata",
        "Small brain",
        "Uygulama",
    ]


def test_the_admin_ui_opens_only_after_the_last_service_turned_green(launcher, capsys):
    assert run.start(8081, 8090, browser=True) == 0
    out = capsys.readouterr().out
    url = "http://127.0.0.1:8090/admin"
    assert out.rindex("✓") < out.index(url)
    assert launcher["opened"] == [url]


def test_check_marks_are_green_on_a_console_and_plain_when_redirected(monkeypatch):
    class Console:
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stdout", Console())
    assert run._green("OCR ✓") == f"{run.GREEN}OCR ✓{run.RESET}"
    monkeypatch.setenv("NO_COLOR", "1")
    assert run._green("OCR ✓") == "OCR ✓"


def test_check_marks_stay_plain_text_in_a_redirected_run(launcher, capsys):
    # a log file or a piped console has to read "OCR ✓", not the escape codes
    assert run.start(8081, 8090, browser=False) == 0
    out = capsys.readouterr().out
    assert run.GREEN not in out and checks(out)


# --- a service that never heals ---


def test_a_child_that_never_heals_names_its_log_and_the_retry_command(launcher, capsys):
    launcher["down"].add(config.ocr_base_url())

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out
    failed = out.index("hazır olmadı")
    assert failed < out.index(str(run.log_path("ocr")), failed)
    assert "python run.py" in out
    assert launcher["opened"] == []
    assert sorted(launcher["killed"]) == sorted(child.pid for _, _, child in launcher["spawned"])


def test_a_strata_that_never_answers_names_the_process_to_start(launcher, monkeypatch, capsys):
    monkeypatch.setenv("STRUCTURER_BACKEND", "strata")
    launcher["down"].add(config.strata_base_url())

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("Strata") and "✗" in line for line in lines(out))
    assert config.strata_base_url() in out
    assert "python run.py" in out
    assert any(line.startswith("OCR") and "✓" in line for line in lines(out))
    assert launcher["opened"] == []
    assert sorted(launcher["killed"]) == sorted(child.pid for _, _, child in launcher["spawned"])


def test_a_cpu_only_box_running_the_small_brain_never_waits_for_strata(launcher, monkeypatch, capsys):
    monkeypatch.setenv("STRUCTURER_BACKEND", "small")
    launcher["down"].add(config.strata_base_url())

    assert run.start(8081, 8090, browser=True) == 0
    out = capsys.readouterr().out
    assert "Strata" not in out
    assert [label(line) for line in checks(out)] == ["OCR", "Small brain", "Uygulama"]


def test_a_small_brain_that_never_heals_names_its_own_log(launcher, capsys):
    launcher["down"].add(config.small_brain_base_url())

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("Small brain") and "✗" in line for line in lines(out))
    assert str(run.log_path("small-brain")) in out
    assert launcher["opened"] == []
    assert sorted(launcher["killed"]) == sorted(child.pid for _, _, child in launcher["spawned"])
