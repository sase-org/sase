"""Shared helpers for notification-store facade tests."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from tests._rust_extension_module_helpers import (
    patch_rust_extension,
)

from sase.notifications.models import Notification

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "notifications"
    / "store_contract.jsonl"
)


def _notification(
    id: str,
    *,
    sender: str = "test",
    action: str | None = None,
    tags: list[str] | None = None,
    read: bool = False,
    muted: bool = False,
    snooze_until: str | None = None,
    resurfaced_at: str | None = None,
) -> Notification:
    return Notification(
        id=id,
        timestamp="2026-04-30T12:00:00+00:00",
        sender=sender,
        notes=["note"],
        tags=tags or [],
        action=action,
        read=read,
        muted=muted,
        snooze_until=snooze_until,
        resurfaced_at=resurfaced_at,
    )


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    patch_rust_extension(monkeypatch, fake)


def _skip_without_notification_bindings(
    binding_name: str = "read_notifications_snapshot",
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, binding_name):
        pytest.skip(f"sase_core_rs is too old (no {binding_name} binding).")
