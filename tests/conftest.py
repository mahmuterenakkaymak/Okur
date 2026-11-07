"""Suite-wide isolation the M8 gate needs: a test's env dies with the test.

``scripts/smoke_e2e._stage2_env`` moves config's stage-2 servers onto a stub by
writing ``os.environ`` and restoring what it took back — that is how a smoke
drives a real process. ``tests/test_cutover_backend.py`` calls it directly to
pin *which* keys it moves, so the stub urls outlive that test and the next
file's default-port assertion reads ``127.0.0.1:5599`` instead of 8080 (config
reads the env on every call, PLAN contract 11). Handing the environment back
after each test is what lets any test move a config value without deciding
which file runs after it.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def environ_restored():
    """Revert every ``os.environ`` change a test — or the code it ran — made."""
    once = os.environ.copy()
    yield
    for name in set(once) | set(os.environ):
        if os.environ.get(name) != once.get(name):
            if name in once:
                os.environ[name] = once[name]
            else:
                del os.environ[name]
