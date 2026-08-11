"""Tests for the SASE process-global cleanup fixture helpers."""

from __future__ import annotations

import os

from tests._sase_global_state_isolation import (
    restore_sase_environment,
    snapshot_sase_environment,
)


def test_restore_sase_environment_restores_changed_added_and_removed_keys(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_EXISTING", "before")
    monkeypatch.setenv("UNPREFIXED_EXISTING", "before")
    baseline = snapshot_sase_environment()
    monkeypatch.setenv("SASE_EXISTING", "after")
    monkeypatch.setenv("SASE_ADDED", "value")
    monkeypatch.setenv("UNPREFIXED_ADDED", "value")
    monkeypatch.delenv("SASE_EXISTING", raising=False)
    monkeypatch.delenv("UNPREFIXED_EXISTING", raising=False)
    monkeypatch.setenv("CODEX_ADDED", "value")

    restore_sase_environment(baseline)

    assert os.environ["SASE_EXISTING"] == "before"
    assert os.environ["UNPREFIXED_EXISTING"] == "before"
    assert "SASE_ADDED" not in os.environ
    assert "UNPREFIXED_ADDED" not in os.environ
    assert "CODEX_ADDED" not in os.environ
