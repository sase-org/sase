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


def test_restore_sase_environment_does_not_drop_session_detach_scope_disable(
    monkeypatch,
) -> None:
    """Session-scoped cgroup-escape guards must survive per-test env restore.

    ``pytest_runtest_protocol`` snapshots before the first test's session
    fixtures run, then restores afterward. If these keys were tracked, that
    restore would wipe ``SASE_DETACH_SCOPE_DISABLE`` for every later test and
    spawn real ``systemd-run`` scopes inside a SASE agent cgroup.
    """
    monkeypatch.setenv("SASE_DETACH_SCOPE_DISABLE", "1")
    monkeypatch.setenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", "1")
    baseline = snapshot_sase_environment()
    assert "SASE_DETACH_SCOPE_DISABLE" not in baseline
    assert "SASE_AXE_DISABLE_SYSTEMD_SCOPE" not in baseline

    restore_sase_environment(baseline)

    assert os.environ.get("SASE_DETACH_SCOPE_DISABLE") == "1"
    assert os.environ.get("SASE_AXE_DISABLE_SYSTEMD_SCOPE") == "1"
