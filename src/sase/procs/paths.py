"""Canonical durable proc paths."""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_subdir

PROCS_SUBDIR = "procs"
PROC_STORE_FILENAME = "procs.jsonl"
PROC_LOGS_SUBDIR = "logs"


def procs_dir() -> Path:
    """Return ``~/.sase/procs`` (or the active ``SASE_HOME`` equivalent)."""
    return sase_subdir(PROCS_SUBDIR)


def proc_store_path() -> Path:
    """Return the Rust-owned proc JSONL path."""
    return procs_dir() / PROC_STORE_FILENAME


def proc_logs_dir() -> Path:
    """Return the directory containing per-proc combined logs."""
    return procs_dir() / PROC_LOGS_SUBDIR


__all__ = ["proc_logs_dir", "proc_store_path", "procs_dir"]
