"""One live snapshot of the machine: model servers, VRAM, queue depth.

The three model servers are the only things here that can be down, so each
probe is one cheap GET with a short timeout and a verdict that never raises:
the status page has to answer even when every server it reports on is off.
The stage-2 probe follows the configured brain, so a CPU-only box shows its
small brain rather than a permanent red Strata.
VRAM comes from nvidia-smi when the tool exists and reads as unavailable
when it does not — a CPU-only box has nothing to show, and that is not an
error.
"""
from __future__ import annotations

import subprocess
import time

import httpx

from app import config, db

# OpenAI-compatible model listing: llama-server, Strata and Unsloth Studio
# all answer it, so one path probes all three.
PROBE_PATH = "/v1/models"


def probe_service(
    base_url: str, transport: httpx.BaseTransport | None = None
) -> dict:
    """ok + latency for one server; unreachable or non-200 reads as not ok."""
    ok = False
    start = time.perf_counter()
    try:
        with httpx.Client(
            transport=transport, timeout=config.probe_timeout()
        ) as client:
            ok = client.get(f"{base_url}{PROBE_PATH}").status_code == 200
    except httpx.HTTPError:
        pass
    ms = int((time.perf_counter() - start) * 1000)
    return {"ok": ok, "latency_ms": ms if ok else None}


def stage2_base_url() -> str:
    """Base url of the stage-2 brain that is configured.

    Contract 9 froze the payload's key names, so the "strata" key reports
    whichever brain stage 2 actually runs: the small brain on :8100 when
    STRUCTURER_BACKEND=small, Strata otherwise (PLAN.md run-2 R4).
    """
    if config.structurer_backend() == "small":
        return config.small_brain_base_url()
    return config.strata_base_url()


def vram_info() -> dict:
    """Used/total MB from nvidia-smi (first GPU); no tool is not an error."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        satir = next((s for s in proc.stdout.splitlines() if s.strip()), "")
        kullanilan, toplam = (int(parca) for parca in satir.split(",")[:2])
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"used_mb": None, "total_mb": None, "ok": False}
    return {"used_mb": kullanilan, "total_mb": toplam, "ok": True}


def probe_all(conn, transport: httpx.BaseTransport | None = None) -> dict:
    """The status payload (PLAN.md contract 9) for this very moment."""
    return {
        "ocr": probe_service(config.ocr_base_url(), transport),
        "strata": probe_service(stage2_base_url(), transport),
        "unsloth": probe_service(config.unsloth_base_url(), transport),
        "vram": vram_info(),
        "queue": db.queue_depth(conn),
    }
