"""Shared fixtures for the direct-Rust vcs_log facade test family."""

from __future__ import annotations

import importlib
import types
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.vcs_log_wire import VcsCommitWire

from ._rust_extension_module_helpers import (
    evict_rust_extension,
    install_fake_rust_extension,
)


def commit(
    full: str, ts: int, subject: str = "s", parent_ids: tuple[str, ...] = ()
) -> VcsCommitWire:
    return VcsCommitWire(
        full_id=full,
        short_id=full[:7],
        author_name="bryan",
        author_email="bryan@example.com",
        timestamp=ts,
        parent_ids=parent_ids,
        subject=subject,
        body="",
    )


def force_no_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    evict_rust_extension(monkeypatch)
    real_import_module = importlib.import_module

    def fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == RUST_EXTENSION_MODULE_NAME:
            raise ImportError(f"No module named {name!r}")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail)


def install_fake_module(
    monkeypatch: pytest.MonkeyPatch, **bindings: Any
) -> types.ModuleType:
    return install_fake_rust_extension(monkeypatch, **bindings)
