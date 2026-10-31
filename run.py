"""One-command launcher: llama-server (OCR) + uvicorn (app) + the queue worker.

    python run.py                                             # start, open admin UI
    python run.py --ocr-port 9001 --app-port 9000 --no-browser
    python run.py --stop                                      # stop from anywhere

run.py supervises the two servers this stack needs and nothing else: it never
downloads a model or builds a database. llama-server serves the PaddleOCR-VL
GGUF with -ngl 0 by default (PLAN decision 2: CPU OCR coexists with Strata's
32 GB, OCR_NGL flips it to GPU), uvicorn serves app.main:create_app, and both
have to answer /health within config.startup_wait_s() before the launcher calls
itself up. The queue worker thread lives here because the app factory does not
own it — without it an upload would sit in the queue forever.

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

import httpx

from app import config
from app.queue_worker import QueueWorker

HEALTH_PATH = "/health"
POLL_S = 0.25
TERMINATE_GRACE_S = 5.0

# app first: stop feeding the queue before pulling the model server out.
SERVICES = ("app", "ocr")
LABELS = {"app": "Uygulama", "ocr": "OCR"}


def _say(step: str, detail: str) -> None:
    print(f"{step:<13} {detail}", flush=True)


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


def app_command(app_port: int | None = None) -> list[str]:
    port = config.app_port() if app_port is None else app_port
    return [
        sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
        "--host", config.app_host(),
        "--port", str(port),
        "--log-level", "warning",
    ]


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
    base_url: str, timeout: float, transport: httpx.BaseTransport | None = None,
    process: subprocess.Popen | None = None,
) -> bool:
    """True once /health answers 200; a process that already exited is final."""
    deadline = time.monotonic() + timeout
    with httpx.Client(transport=transport, timeout=config.probe_timeout()) as client:
        while True:
            try:
                if client.get(f"{base_url}{HEALTH_PATH}").status_code == 200:
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

    commands = {"ocr": ocr_command(ocr_port), "app": app_command(app_port)}
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
        bases = {"ocr": config.ocr_base_url(), "app": config.app_base_url()}
        for name in SERVICES:
            left = max(0.0, deadline - time.monotonic())
            if wait_healthy(bases[name], left, process=children[name]):
                _say(LABELS[name], "✓")
            else:
                _say(LABELS[name], f"✗ {config.startup_wait_s()} sn içinde hazır olmadı")
                _say("log", str(log_path(name)))
                _say("tekrar dene", "python run.py")
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
