"""run.py: the launcher's commands, health gate, pid/log bookkeeping and --stop.

The three servers are faked at the spawn seam (a launcher test must not need a
GGUF or a free port); everything else — argument building, the pid and log
files, process liveness and killing, the exit codes — is the real thing.
"""
import os
import pathlib
import subprocess
import sys
import time
import webbrowser

import httpx
import pytest

import run
from app import config

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
    # T78 preflights the small brain before spawning it; these tests describe an
    # installed box with a free 8100 (tests/test_launcher_small_brain.py covers
    # the two red lines).
    monkeypatch.setattr(config, "small_brain_ready", lambda: True)
    monkeypatch.setattr(run, "_port_free", lambda host, port: True)


def flag_value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


# --- the three command lines ---


def test_ocr_command_serves_the_gguf_with_mmproj_and_chat_template():
    command = run.ocr_command()
    assert command[0] == str(config.llama_server_path())
    assert flag_value(command, "-m") == str(config.ocr_model_path())
    assert flag_value(command, "--mmproj") == str(config.ocr_mmproj_path())
    assert flag_value(command, "--chat-template-file") == str(
        config.ocr_chat_template_path()
    )
    assert "--no-webui" in command


def test_ocr_command_runs_on_cpu_unless_ocr_ngl_says_otherwise(monkeypatch):
    assert flag_value(run.ocr_command(), "-ngl") == "0"
    monkeypatch.setenv("OCR_NGL", "35")
    assert flag_value(run.ocr_command(), "-ngl") == "35"


def test_ocr_command_takes_its_port_from_the_flag():
    assert flag_value(run.ocr_command(), "--port") == "8081"
    assert flag_value(run.ocr_command(9001), "--port") == "9001"
    assert flag_value(run.ocr_command(), "--host") == config.ocr_host()


def test_app_command_serves_the_app_factory_with_uvicorn():
    command = run.app_command(9000)
    assert command[:5] == [
        sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
    ]
    assert flag_value(command, "--port") == "9000"
    assert flag_value(run.app_command(), "--port") == "8090"


def test_small_brain_command_serves_its_gguf_as_a_second_llama_server():
    command = run.small_brain_command()
    assert command[0] == str(config.small_brain_server_path())
    assert flag_value(command, "-m") == str(config.small_brain_model_path())
    assert flag_value(command, "--mmproj") == str(config.small_brain_mmproj_path())
    assert "--no-webui" in command


def test_small_brain_command_fits_a_cpu_only_box_and_one_receipt_image():
    command = run.small_brain_command()
    assert flag_value(command, "--host") == "127.0.0.1"
    assert flag_value(command, "--port") == "8100"
    assert flag_value(command, "-c") == "8192"
    assert flag_value(command, "-ngl") == "0"
    assert flag_value(command, "--image-min-tokens") == "1024"
    assert flag_value(command, "--image-max-tokens") == "1024"
    assert flag_value(command, "--temp") == "0"


def test_small_brain_command_moves_with_the_base_url_the_app_will_call(monkeypatch):
    monkeypatch.setenv("SMALL_BRAIN_BASE_URL", "http://127.0.0.1:9100")
    assert flag_value(run.small_brain_command(), "--port") == "9100"


# --- where the launcher keeps its bookkeeping ---


def test_pids_and_logs_live_under_the_data_dir():
    assert run.pid_path("ocr") == config.data_dir() / "ocr.pid"
    assert run.pid_path("small-brain") == config.data_dir() / "small-brain.pid"
    assert run.log_path("app") == config.data_dir() / "logs" / "app.log"
    assert run.log_path("small-brain") == config.data_dir() / "logs" / "small-brain.log"


def test_spawn_appends_the_child_output_to_its_own_log():
    child = run._spawn("ocr", [sys.executable, "-c", "print('llama hazir')"])
    assert child.wait(timeout=30) == 0
    assert "llama hazir" in run.log_path("ocr").read_text(encoding="utf-8")


# --- the health gate ---


def stub_transport(status: int) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status))


def test_wait_healthy_passes_as_soon_as_health_answers_200():
    assert run.wait_healthy("http://127.0.0.1:9", 5.0, transport=stub_transport(200))


def test_wait_healthy_uses_the_whole_budget_on_a_server_that_stays_loading():
    started = time.monotonic()
    healthy = run.wait_healthy("http://127.0.0.1:9", 0.4, transport=stub_transport(503))
    assert healthy is False
    assert 0.2 < time.monotonic() - started < 3.0


def test_wait_healthy_gives_up_at_once_when_the_process_already_exited():
    class Dead:
        def poll(self):
            return 1

    started = time.monotonic()
    healthy = run.wait_healthy(
        "http://127.0.0.1:9", 60.0, transport=stub_transport(503), process=Dead()
    )
    assert healthy is False and time.monotonic() - started < 3.0


# --- --stop ---


def sleep_child() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])


def track(name: str, pid: int) -> None:
    run.pid_path(name).parent.mkdir(parents=True, exist_ok=True)
    run.pid_path(name).write_text(str(pid), encoding="utf-8")


def test_stop_kills_the_tracked_processes_and_clears_their_pid_files(capsys):
    app, ocr, brain = sleep_child(), sleep_child(), sleep_child()
    track("app", app.pid)
    track("ocr", ocr.pid)
    track("small-brain", brain.pid)

    assert run.stop() == 0
    for name, child in (("app", app), ("ocr", ocr), ("small-brain", brain)):
        child.wait(timeout=10)
        assert run._alive(child.pid) is False
        assert not run.pid_path(name).exists()
    assert "durduruldu" in capsys.readouterr().out


def test_stop_is_not_an_error_when_nothing_is_tracked(capsys):
    assert run.stop() == 0
    assert "çalışmıyor" in capsys.readouterr().out


def test_stop_clears_a_pid_whose_process_is_already_gone():
    child = sleep_child()
    child.terminate()
    child.wait(timeout=10)
    track("ocr", child.pid)

    assert run.stop() == 0
    assert not run.pid_path("ocr").exists()


def test_alive_tells_a_running_process_from_a_finished_one():
    child = sleep_child()
    assert run._alive(child.pid) is True
    child.terminate()
    child.wait(timeout=10)
    assert run._alive(child.pid) is False


# --- start() ---


class FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None


class FakeWorker:
    started = 0
    stopped = 0

    def __init__(self, db_path=None, **kwargs):
        pass

    def start(self):
        FakeWorker.started += 1

    def stop(self, timeout: float = 10.0):
        FakeWorker.stopped += 1


class Launcher:
    """What the faked-out start() did: which children, which kills, which url."""

    def __init__(self, state: dict) -> None:
        self.state = state

    @property
    def spawned(self):
        return self.state["spawned"]

    @property
    def killed(self):
        return self.state["killed"]

    @property
    def opened(self):
        return self.state["opened"]

    @property
    def children(self):
        return {name: child.pid for name, _, child in self.spawned}

    def command(self, name: str) -> list[str]:
        return next(args for service, args, _ in self.spawned if service == name)

    @property
    def tracked(self):
        """The pid files as they stood while the stack was up."""
        return self.state["tracked"]

    def set_healthy(self, value: bool) -> None:
        self.state["healthy"] = value


@pytest.fixture
def launcher(monkeypatch):
    """start() with the children, the health gate and the wait faked out."""
    FakeWorker.started = FakeWorker.stopped = 0
    state = {"healthy": True, "spawned": [], "killed": [], "opened": [], "tracked": {}}

    def fake_spawn(name, args):
        child = FakeChild(987_000 + len(state["spawned"]))
        state["spawned"].append((name, args, child))
        return child

    monkeypatch.setattr(run, "_spawn", fake_spawn)
    monkeypatch.setattr(run, "wait_healthy", lambda *a, **k: state["healthy"])
    monkeypatch.setattr(
        run, "_terminate", lambda pid, grace=0.0: state["killed"].append(pid) or True
    )
    monkeypatch.setattr(run, "QueueWorker", FakeWorker)
    def fake_wait(children):
        state["tracked"] = {
            name: run.pid_path(name).read_text() for name in run.SERVICES
        }

    monkeypatch.setattr(run, "_wait_for_children", fake_wait)
    monkeypatch.setattr(webbrowser, "open", state["opened"].append)
    return Launcher(state)


def test_start_tracks_pids_starts_the_worker_and_reports_the_admin_url(launcher, capsys):
    assert run.start(8081, 8090, browser=True) == 0
    assert {name for name, _, _ in launcher.spawned} == {"ocr", "app", "small-brain"}
    assert launcher.tracked == {
        name: str(pid) for name, pid in launcher.children.items()
    }
    assert (FakeWorker.started, FakeWorker.stopped) == (1, 1)
    out = capsys.readouterr().out
    # D7 roll-call: OCR, Strata, Small brain and Uygulama, though only three are children
    assert out.count("✓") == 4
    assert "http://127.0.0.1:8090/admin" in out
    assert launcher.opened == ["http://127.0.0.1:8090/admin"]
    assert sorted(launcher.killed) == sorted(launcher.children.values())
    assert all(run.pid_path(name).exists() is False for name in run.SERVICES)


def test_no_browser_starts_the_same_stack_without_opening_one(launcher):
    assert run.start(8081, 8090, browser=False) == 0
    assert launcher.opened == []


def test_start_names_the_log_and_the_retry_command_when_a_service_never_heals(
    launcher, capsys
):
    launcher.set_healthy(False)

    assert run.start(8081, 8090, browser=True) == 1
    out = capsys.readouterr().out
    assert str(run.log_path("app")) in out
    assert "python run.py" in out
    assert launcher.opened == []
    assert sorted(launcher.killed) == sorted(launcher.children.values())
    assert all(run.pid_path(name).exists() is False for name in run.SERVICES)


def test_ctrl_c_stops_the_small_brain_with_the_rest_of_the_stack(launcher, monkeypatch):
    def interrupted(children):
        raise KeyboardInterrupt

    monkeypatch.setattr(run, "_wait_for_children", interrupted)

    assert run.start(8081, 8090, browser=False) == 0
    assert launcher.killed == [launcher.children[name] for name in run.SERVICES]
    assert not run.pid_path("small-brain").exists()


def test_start_refuses_before_spawning_when_a_model_file_is_missing(launcher, monkeypatch, capsys):
    monkeypatch.setattr(
        run, "required_files", lambda: [pathlib.Path("vendor/llama/olmayan.exe")]
    )
    assert run.start(8081, 8090, browser=True) == 1
    assert "olmayan.exe" in capsys.readouterr().out
    assert launcher.spawned == [] and launcher.killed == []


def test_start_passes_the_ports_to_the_app_child_and_its_own_worker(launcher, monkeypatch):
    # registered here so teardown clears them: start() writes the environment
    monkeypatch.setenv("OCR_PORT", "1")
    monkeypatch.setenv("APP_PORT", "1")

    assert run.start(9001, 9000, browser=False) == 0
    assert os.environ["OCR_PORT"] == "9001" and os.environ["APP_PORT"] == "9000"
    assert flag_value(launcher.command("ocr"), "--port") == "9001"
    assert flag_value(launcher.command("app"), "--port") == "9000"


# --- main() ---


def test_main_routes_the_flags_to_start_and_stop(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "start", lambda ocr, app, browser: calls.append((ocr, app, browser)) or 0)
    monkeypatch.setattr(run, "stop", lambda: calls.append("stop") or 0)

    assert run.main(["--ocr-port", "9001", "--app-port", "9000", "--no-browser"]) == 0
    assert calls[-1] == (9001, 9000, False)
    assert run.main(["--stop"]) == 0
    assert calls[-1] == "stop"
    assert run.main([]) == 0
    assert calls[-1] == (config.ocr_port(), config.app_port(), True)
