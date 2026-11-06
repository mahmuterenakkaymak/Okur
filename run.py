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
A small brain that cannot be started is the one deliberate exception: no files
or a busy port is a red ✗ line naming the installer to run or the process to
stop, and the app comes up without it.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import ipaddress
import os
import pathlib
import signal
import socket
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

# what to tell an operator whose box has no small brain yet (T80 lands the script)
INSTALL_SCRIPT = "scripts\\install_small_brain.ps1"

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


def small_brain_is_local() -> bool:
    """Whether the small brain's host is this box, and so ours to spawn.

    A SMALL_BRAIN_BASE_URL that names another machine means the brain runs and
    is started there: a local llama-server asked to bind that address only dies
    on the way to the health gate. ASSUMPTION: "this box" is loopback or the
    machine's own name; anything else is somebody else's host.
    """
    host = small_brain_host().lower()
    if host == "localhost":
        return True
    try:
        if host == (socket.gethostname() or "").lower():
            return True
    except OSError:
        pass
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def small_brain_is_stage2() -> bool:
    """Whether the small brain is the stage-2 backend right now.

    Mirror image of the Strata line: as stage 2 a brain that never turns healthy
    fails the start, since every job would die there; while Strata runs stage 2
    the brain is a note — its ✗ line prints, the stack serves and exits 0.
    """
    return config.structurer_backend() == "small"


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


def _port_free(host: str, port: int) -> bool:
    """True when this box can still take host:port.

    A bind is the only probe every OS answers without an administrative tool,
    and SO_REUSEADDR stays off because on Windows it lets a busy port bind
    anyway. Any error that is not "already in use" — a base url naming another
    machine, say — reads as free, leaving the health gate to explain that.
    """
    try:
        with socket.socket() as probe:
            probe.bind((host, port))
    except OSError as exc:
        return exc.errno != errno.EADDRINUSE
    return True


def _listener_pids(port: int) -> list[int]:
    """PIDs listening on the port, from the OS's own tool; empty when there is
    no tool to ask. Never raises — a launcher that cannot name the holder still
    names the port and starts the app."""
    if os.name == "nt":
        cmd = ["netstat", "-ano"]
    else:
        cmd = ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if os.name == "nt":
            #   TCP    127.0.0.1:8100    0.0.0.0:0              LISTENING    4321
            if len(parts) != 5 or parts[3] != "LISTENING":
                continue
            if parts[1].rpartition(":")[2] != str(port):
                continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def _process_name(pid: int) -> str:
    """Image name of a pid; "" when the OS will not say."""
    cmd = (
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"]
        if os.name == "nt"
        else ["ps", "-p", str(pid), "-o", "comm="]
    )
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    rows = [line for line in out.strip().splitlines() if line]
    if not rows or "No Mapping" in rows[0] or "no such process" in rows[0].lower():
        return ""
    return rows[0].split(",")[0].strip('"')


def _port_holder(port: int) -> str:
    """Who to blame for a busy port: "pid 4321 (llama-server.exe)"."""
    pids = _listener_pids(port)
    if not pids:
        return "bilinmeyen bir süreç"
    return ", ".join(f"pid {pid} ({_process_name(pid) or 'bilinmiyor'})" for pid in pids[:3])


def small_brain_block() -> tuple[str, list[tuple[str, str]]] | None:
    """(reason, help lines) when the small brain must not be spawned; None to
    start it normally.

    Both reads happen before the spawn, and that is the whole point: a missing
    GGUF leaves a child dying on startup and a busy port loses the race, so the
    ✗ would name nothing. Neither is fatal — stage 1, the queue and the admin UI
    work without stage 2.
    """
    if not config.small_brain_ready():
        return (
            "model dosyaları yok",
            [("kurulum", INSTALL_SCRIPT), ("dizin", str(config.small_brain_dir()))],
        )
    port = config.small_brain_port()
    if not _port_free(small_brain_host(), port):
        return (
            f"port {port} dolu",
            [("işgalci", _port_holder(port)), ("durdur", "python run.py --stop")],
        )
    return None


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
    a CPU-only box has no Strata to wait for. The small brain line is there
    whatever stage 2 runs — its child on a small box, an outer process on any
    other — but it is a requirement only while it is stage 2 (small_brain_is_stage2).
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


def _failure_help(name: str, base: str, owned: bool) -> None:
    """What to read and what to run again, printed under a ✗ line.

    A child this launcher owns has a log of its own; anything else — Strata, or
    a small brain whose base url names another machine — is started outside it,
    so the operator gets the endpoint to start instead.
    ASSUMPTION: a stage-2 server down fails the start only when it is the
    configured stage-2 backend, since every job would die there otherwise.
    """
    if owned:
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
    # a brain on another machine is waited for like Strata: never spawned here,
    # nothing is preflighted on this box for it, and its ✗ names the endpoint
    # rather than a log that stays empty.
    remote_brain = not small_brain_is_local()
    blocked = None if remote_brain else small_brain_block()
    brain_is_stage2 = small_brain_is_stage2()
    children: dict[str, subprocess.Popen] = {}
    worker = None
    try:
        for name in SERVICES:
            if name == "small-brain" and (blocked is not None or remote_brain):
                # no child, so no pid file either — --stop must not kill a
                # process this launcher never started.
                pid_path(name).unlink(missing_ok=True)
                continue
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
            if name == "small-brain" and blocked is not None:
                reason, help_lines = blocked
                _say(LABELS[name], f"✗ {reason}")
                for step, detail in help_lines:
                    _say(step, detail)
                continue
            if name not in children:
                _say(LABELS[name], f"bekleniyor… ({base})")
            left = max(0.0, deadline - time.monotonic())
            if wait_healthy(base, left, path, process=children.get(name)):
                _say(LABELS[name], _green("✓"))
            else:
                _say(LABELS[name], f"✗ {config.startup_wait_s()} sn içinde hazır olmadı")
                _failure_help(name, base, name in children)
                if name != "small-brain" or brain_is_stage2:
                    return 1
        url = f"{config.app_base_url()}/admin"
        _say("admin", url)
        _say("durdurmak için", "python run.py --stop")
        if browser:
            webbrowser.open(url)
        # ASSUMPTION: the launcher stays in the foreground as the supervisor;
        # Ctrl+C here or --stop from another terminal is what ends the stack.
        _wait_for_children(children)
        # ASSUMPTION: "does not claim success" means the ✗ line plus a nonzero
        # exit once the stack ends — the app served receipts the whole time.
        return 1 if blocked and brain_is_stage2 else 0
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
