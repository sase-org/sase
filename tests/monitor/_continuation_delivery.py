"""Shared sandbox for continuation-delivery tests (public names only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.monitor.continuation_delivery import DELIVERY_CRASH_ENV


@pytest.fixture(autouse=True)
def continuation_delivery_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sandbox ``SASE_HOME`` and clear delivery-crash markers."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv(DELIVERY_CRASH_ENV, raising=False)
