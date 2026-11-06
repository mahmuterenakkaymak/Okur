"""One-command launcher: llama-server (OCR) + uvicorn (app) + the queue worker.

    python run.py                                             # start, open admin UI
    python run.py --ocr-port 9001 --app-port 9000 --no-browser
    python run.py --stop                                      # stop from anywhere

run.py supervises the three servers this stack needs and nothing else: it never
downloads a model or builds a database. llama-server serves the PaddleOCR-VL
GGUF with -ngl 0 by default (PLAN decision 2: CPU OCR coexists with Strata's
32 GB, OCR_NGL flips it to GPU) and, on 8100, the small brain that runs stage 2
once STRUCTURER_BACKEND says small; uvicorn serves app.main:create_app. Every service then gets its own
green ✓ line the moment it turns healthy (PLAN D7): the three children on
/health, Strata — stage 2 only when STRUCTURER_BACKEND says so, and a process
this launcher does not own — on the model listing. The queue worker thread lives
here because the app factory does not own it — without it an upload would sit in
the queue forever.

Child PIDs go to data/<name>.pid and their output to data/logs/<name>.log, so
--stop works from another terminal and a failed start names the log to read.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import pathlib
import signal
import subprocess
import sys
import time
import webbrowser
from urllib.parse import urlparse

import httpx

from app import config, status
from app.queue_worker import QueueWorker

# the small brain is a receipt-structuring run at most: 8k context, one image
# at a fixed token budget, and no GPU layers (the box that runs it has none).
# ASSUMPTION: fixed rather than env-configurable — unlike OCR, it has one job.
SMALL_BRAIN_CTX = "8192"
SMALL_BRAIN_IMAGE_TOKENS = "1024"

HEALTH_PATH = "/health"
POLL_S = 0.25
TERMINATE_GRACE_S = 5.0
GREEN, RESET = "\x1b[32m", "\x1b[0m"

# app first: stop feeding the queue before pulling the model servers out.
SERVICES = ("app", "ocr", "small-brain")
LABELS = {
    "app": "Uygulama",
    "ocr": "OCR",
    "strata": "Strata",
    "small-brain": "Small brain",
}


def _say(step: str, detail: str) -> None:
    print(f"{step:<13} {detail}", flush=True)


def _green(text: str) -> str:
    """ANSI green on a console; plain text when redirected or under NO_COLOR."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"{GREEN}{text}{RESET}"


def pid_path(name: str) -> pathlib.Path:
    return config.data_dir() / f"{name}.pid"


def log_path(name: str) -> pathlib.Path:
    return config.log_dir() / f"{name}.log"


def required_files() -> list[pathlib.Path]:
    """Everything llama-server needs to answer at all; a missing one is a
    config or download problem, and saying so beats a 60 s health timeout."""
    return [
        config.llama_server_path(),
        config.ocr_model_path(),
        config.ocr_mmproj_path(),
        config.ocr_chat_template_path(),
    ]


def ocr_command(ocr_port: int | None = None) -> list[str]:
    port = config.ocr_port() if ocr_port is None else ocr_port
    return [
        str(config.llama_server_path()),
        "-m", str(config.ocr_model_path()),
        "--mmproj", str(config.ocr_mmproj_path()),
        "--chat-template-file", str(config.ocr_chat_template_path()),
        "--host", config.ocr_host(),
        "--port", str(port),
        "-c", str(config.ocr_ctx()),
        "-ngl", str(config.ocr_ngl()),
        "--temp", "0",
        "--no-webui",
    ]


def small_brain_host() -> str:
    """Host of the small brain, read off its base url so one env value moves
    the launcher and the stage-2 client together; junk means loopback."""
    return urlparse(config.small_brain_base_url()).hostname or "127.0.0.1"


def small_brain_command(port: int | None = None) -> list[str]:
    port = config.small_brain_port() if port is None else port
    return [
        str(config.small_brain_server_path()),
        "-m", str(config.small_brain_model_path()),
        "--mmproj", str(config.small_brain_mmproj_path()),
        "--host", small_brain_host(),
        "--port", str(port),
        "-c", SMALL_BRAIN_CTX,
        "-ngl", "0",
        "--image-min-tokens", SMALL_BRAIN_IMAGE_TOKENS,
        "--image-max-tokens", SMALL_BRAIN_IMAGE_TOKENS,
        "--temp", "0",
        "--no-webui",
    ]


def app_command(app_port: int | None = None) -> list[str]:
    port = config.app_port() if app_port is None else app_port
    return [
        sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
        "--host", config.app_host(),
        "--port", str(port),
        "--log-level", "warning",
    ]


def roll_call() -> list[tuple[str, str, str]]:
    """(name, base_url, health path) in the order the roll-call reads (D7).

    Strata is a separate process (OPERATIONS.md → Model paths), so it is waited
    for and never spawned, and only when it is the configured stage-2 backend —
    a CPU-only box has no Strata to wait for. The small brain is this launcher's
    own child, so it is waited for always: a job would die at stage 2 otherwise.
    Both model servers answer the OpenAI model listing rather than /health,
    which is what app/status.py probes for every server.
    """
    entries = [("ocr", config.ocr_base_url(), HEALTH_PATH)]
    if config.structurer_backend() == "strata":
        entries.append(("strata", config.strata_base_url(), status.PROBE_PATH))
    entries.append(("small-brain", config.small_brain_base_url(), status.PROBE_PATH))
    entries.append(("app", config.app_base_url(), HEALTH_PATH))
    return entries


def _spawn(name: str, args: list[str]) -> subprocess.Popen:
    """One child, its output appended to its own log under data/logs.

    A new process group keeps Ctrl+C on the launcher, so the children go
    through _terminate instead of dying mid-request to a console signal.
    """
    path = log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    log = path.open("a", encoding="utf-8")
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    return subprocess.Popen(
        args, stdout=log, stderr=subprocess.STDOUT, cwd=config.ROOT, **group
    )


def wait_healthy(
    base_url: str, timeout: float, path: str = HEALTH_PATH,
    transport: httpx.BaseTransport | None = None,
    process: subprocess.Popen | None = None,
) -> bool:
    """True once the path answers 200; a process that already exited is final."""
    deadline = time.monotonic() + timeout
    with httpx.Client(transport=transport, timeout=config.probe_timeout()) as client:
        while True:
            try:
                if client.get(f"{base_url}{path}").status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                return False
            if process is not None and process.poll() is not None:
                return False
            time.sleep(POLL_S)


def _alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _wait_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while _alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _terminate(pid: int, grace: float = TERMINATE_GRACE_S) -> bool:
    """Stop one tracked process, whole tree included; True when it is gone."""
    if not _alive(pid):
        return True
    if os.name == "nt":
        # a console process takes no graceful signal, so go straight to /F
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True
        )
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            return True
        if not _wait_gone(pid, grace):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    return _wait_gone(pid, grace)


def _tracked(name: str) -> int | None:
    try:
        return int(pid_path(name).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def stop() -> int:
    """Kill whatever the last start tracked and clear its pid file."""
    failed = []
    for name in SERVICES:
        label = LABELS[name]
        pid = _tracked(name)
        if pid is None:
            _say(label, "çalışmıyor")
            continue
        path = pid_path(name)
        path.unlink(missing_ok=True)
        if _terminate(pid):
            _say(label, f"durduruldu (pid {pid})")
        else:
            _say(label, f"durdurulamadi (pid {pid} hâlâ ayakta)")
            failed.append(name)
    return 1 if failed else 0


def _wait_for_children(children: dict[str, subprocess.Popen]) -> None:
    while any(child.poll() is None for child in children.values()):
        time.sleep(0.5)


def _failure_help(name: str, base: str) -> None:
    """What to read and what to run again, printed under a ✗ line.

    A child has a log of its own; Strata does not — it is started outside this
    launcher, so the operator gets the endpoint to start instead.
    ASSUMPTION: Strata down fails the start as well, since every job would
    otherwise die at stage 2 behind an admin UI that looks healthy.
    """
    if name in SERVICES:
        _say("log", str(log_path(name)))
    else:
        _say("başlat", f"{LABELS[name]} stage 2 dışarıda çalışır → {base}")
    _say("tekrar dene", "python run.py")


def start(ocr_port: int, app_port: int, browser: bool) -> int:
    # the app child and this process's own worker both read the ports back
    # through config, so the flags land in the environment once, here.
    os.environ["OCR_PORT"] = str(ocr_port)
    os.environ["APP_PORT"] = str(app_port)
    config.data_dir().mkdir(parents=True, exist_ok=True)
    missing = [path for path in required_files() if not path.is_file()]
    if missing:
        for path in missing:
            _say("eksik", str(path))
        _say("ayarlar", ".env: LLAMA_SERVER, OCR_MODEL, OCR_MMPROJ, OCR_CHAT_TEMPLATE")
        return 1

    commands = {
        "ocr": ocr_command(ocr_port),
        "app": app_command(app_port),
        "small-brain": small_brain_command(),
    }
    children: dict[str, subprocess.Popen] = {}
    worker = None
    try:
        for name in SERVICES:
            child = _spawn(name, commands[name])
            children[name] = child
            pid_path(name).write_text(str(child.pid), encoding="utf-8")
            _say(LABELS[name], f"başlatılıyor… (log: {log_path(name)})")
        # ASSUMPTION: the launcher hosts the queue worker, since no other
        # production entry point starts one and uploads would never drain.
        worker = QueueWorker(db_path=config.db_path())
        worker.start()
        deadline = time.monotonic() + config.startup_wait_s()
        for name, base, path in roll_call():
            if name not in children:
                _say(LABELS[name], f"bekleniyor… ({base})")
            left = max(0.0, deadline - time.monotonic())
            if wait_healthy(base, left, path, process=children.get(name)):
                _say(LABELS[name], _green("✓"))
            else:
                _say(LABELS[name], f"✗ {config.startup_wait_s()} sn içinde hazır olmadı")
                _failure_help(name, base)
                return 1
        url = f"{config.app_base_url()}/admin"
        _say("admin", url)
        _say("durdurmak için", "python run.py --stop")
        if browser:
            webbrowser.open(url)
        # ASSUMPTION: the launcher stays in the foreground as the supervisor;
        # Ctrl+C here or --stop from another terminal is what ends the stack.
        _wait_for_children(children)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if worker is not None:
            worker.stop()
        for name, child in children.items():
            _terminate(child.pid)
            pid_path(name).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Başlatıcı: llama-server (OCR) + uvicorn (uygulama)."
    )
    parser.add_argument("--ocr-port", type=int, default=config.ocr_port())
    parser.add_argument("--app-port", type=int, default=config.app_port())
    parser.add_argument(
        "--no-browser", action="store_true", help="sağlık kontrolünden sonra tarayıcı açma"
    )
    parser.add_argument(
        "--stop", action="store_true", help="izlenen süreçleri durdur ve pid dosyalarını temizle"
    )
    args = parser.parse_args(argv)
    if args.stop:
        return stop()
    return start(args.ocr_port, args.app_port, browser=not args.no_browser)


if __name__ == "__main__":
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        # the roll-call carries Turkish and ✓; a cp1252 console would kill it
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
