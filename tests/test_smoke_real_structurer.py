"""The smoke gates the shipped stage-2 client, never a stand-in of its own.

app/structurer.py owns the contract prompt, the defensive JSON extraction and
the quality-mode routing; a smoke that hand-rolls its own stage-2 request stays
green while all three break, which is exactly how long its own stand-in
outlived the module it was waiting for.
"""
from __future__ import annotations

import ast

from app import config

TREE = ast.parse((config.ROOT / "scripts" / "smoke_e2e.py").read_text(encoding="utf-8"))


def _imports() -> set[str]:
    """Every module the smoke imports, by dotted name."""
    found = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _defined() -> set[str]:
    """Names the smoke defines itself: its classes and functions."""
    return {
        node.name
        for node in ast.walk(TREE)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }


def test_smoke_imports_the_shipped_structurer():
    assert "app.structurer" in _imports()


def test_smoke_defines_no_stage2_stand_in():
    assert "_HttpStructurer" not in _defined()
