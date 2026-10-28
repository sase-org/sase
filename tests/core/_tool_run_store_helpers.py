"""Shared builders for tool-run store tests."""

from __future__ import annotations

from pathlib import Path


def make_definition() -> dict[str, object]:
    """Return the canonical ``check`` tool definition used by store tests."""
    return {
        "schema_version": 1,
        "name": "check",
        "argv": ["just", "check"],
        "description": "check",
        "stages": "run_silent",
        "inputs": ["Justfile"],
        "env": [],
        "args": "deny",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def make_store_path(tmp_path: Path) -> str:
    """Return the standard tool-run SQLite store path under ``tmp_path``."""
    return str(tmp_path / "tools" / "runs.sqlite")
