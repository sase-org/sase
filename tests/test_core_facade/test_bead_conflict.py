"""Guard tests for the Rust bead event conflict facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core import bead_conflict_facade


def test_manifest_repair_refuses_unsandboxed_pytest_store_before_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe_beads_dir = tmp_path / "production" / "sdd/beads"
    unsafe_beads_dir.mkdir(parents=True)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    def fail_binding(_name: str) -> None:
        raise AssertionError("unsafe manifest repair reached Rust binding")

    monkeypatch.setattr(bead_conflict_facade, "require_rust_binding", fail_binding)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "manifest repair write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(sandbox))

    with pytest.raises(RuntimeError) as exc_info:
        bead_conflict_facade.repair_event_store_manifest(unsafe_beads_dir)

    message = str(exc_info.value)
    assert "repair_event_store_manifest" in message
    assert str(unsafe_beads_dir.resolve()) in message
    assert str(sandbox.resolve()) in message


def test_manifest_repair_allows_sandboxed_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir = tmp_path / "sandbox" / "sdd/beads"
    beads_dir.mkdir(parents=True)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "manifest repair write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path / "sandbox"))

    outcome = bead_conflict_facade.repair_event_store_manifest(beads_dir)

    assert outcome["status"] == "noop"
