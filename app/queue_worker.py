"""SQLite queue consumed by one worker thread: queued -> running -> done/failed.

The queue is the jobs table itself, so a burst of uploads is just rows —
nothing to overflow, and a crash loses nothing: recover() requeues running
jobs (their process is gone) and fails the ones already past the staleness
window, which are more likely poison than bad luck. One thread is the whole
design (PLAN: <=10 workers, <=500 receipts/day), and each thread opens its
own connection because sqlite forbids sharing one across threads.
"""
from __future__ import annotations

import os
import pathlib
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app import config, db, pipeline

POLL_INTERVAL_S = 0.25

Runner = Callable[..., dict[str, Any]]


def recover(conn, *, stale_minutes: int | None = None) -> dict[str, int]:
    """Restart cleanup: a running job belongs to a process that is gone.

    Recent ones were merely interrupted and go back to queued. Ones already
    older than config.stale_job_minutes() were running when the last process
    died too, so they are marked failed for an operator rerun instead of
    restarting into the same crash forever.
    """
    # ASSUMPTION: "requeues running jobs and marks stale failures" splits by
    # age — fresh interruptions retry, stale ones fail.
    minutes = config.stale_job_minutes() if stale_minutes is None else stale_minutes
    cutoff = _cutoff(minutes)
    counts = {"requeued": 0, "failed": 0}
    for job in db.list_jobs(conn, status="running", limit=1000):
        started = job["started_at"] or job["created_at"]
        if started < cutoff:
            db.set_status(
                conn,
                job["id"],
                "failed",
                error=f"stale: interrupted over {minutes} min ago",
            )
            counts["failed"] += 1
        else:
            db.set_status(conn, job["id"], "queued")
            counts["requeued"] += 1
    return counts


def _cutoff(minutes: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class QueueWorker:
    """One daemon thread draining the queue; start() recovers, stop() drains.

    The runner is the pipeline seam (tests inject a fake): it takes the image
    bytes plus quality_mode/worker and returns pipeline.run's bundle. A
    bundle with a non-empty error is a failed job (dead model server, bad
    image); an unreadable receipt carries no error and completes done with
    its verdict, because the pipeline did its job there.
    """

    def __init__(
        self,
        db_path: str | os.PathLike[str] | None = None,
        *,
        runner: Runner | None = None,
        poll_interval: float = POLL_INTERVAL_S,
        stale_minutes: int | None = None,
    ) -> None:
        self._db_path = db_path
        self._runner = pipeline.run if runner is None else runner
        self._poll = poll_interval
        self._stale = stale_minutes
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._local = threading.local()

    def start(self) -> None:
        recover(self._db(), stale_minutes=self._stale)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="queue-worker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Finish the job in flight, then end the loop."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def run_once(self) -> bool:
        """Claim and process the oldest queued job; False when none is left."""
        conn = self._db()
        job = self._claim(conn)
        if job is None:
            return False
        self._process(conn, job)
        return True

    def _claim(self, conn):
        row = conn.execute(
            "SELECT id FROM jobs WHERE status = 'queued'"
            " ORDER BY created_at, rowid LIMIT 1"
        ).fetchone()
        return db.set_status(conn, row["id"], "running") if row else None

    def _process(self, conn, job) -> None:
        try:
            image = pathlib.Path(job["image_path"]).read_bytes()
        except OSError as exc:
            db.set_status(conn, job["id"], "failed", error=f"image: {exc}")
            return
        try:
            bundle = self._runner(
                image,
                quality_mode=job["mode"] == "quality",
                worker=job["worker"],
            )
        except Exception as exc:  # the thread outlives any single job
            db.set_status(
                conn, job["id"], "failed", error=f"{type(exc).__name__}: {exc}"
            )
            return
        # ASSUMPTION: captured_at belongs to the route (not a queue column),
        # so the worker only fills received_at from the row's created_at.
        meta = {**(bundle.get("meta") or {}), "received_at": job["created_at"]}
        if bundle.get("error"):
            db.set_status(conn, job["id"], "failed", error=str(bundle["error"]))
        else:
            db.set_status(
                conn,
                job["id"],
                "done",
                result_json=bundle.get("result"),
                validation_json=bundle.get("validation"),
                meta_json=meta,
                error="",
            )

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                if not self.run_once():
                    self._stop.wait(self._poll)
        finally:
            conn = getattr(self._local, "conn", None)
            if conn is not None:
                conn.close()
                self._local.conn = None

    def _db(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = db.connect(self._db_path)
        return conn
