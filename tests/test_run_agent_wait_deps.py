"""Focused tests for run-agent wait dependency helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.axe.run_agent_wait_deps import refresh_bead_wait_store


def test_refresh_bead_wait_store_honors_off_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locate = MagicMock(return_value=tmp_path / "beads")
    refresh = MagicMock()
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "off")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        locate,
    )
    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", refresh)

    refresh_bead_wait_store("proj")

    locate.assert_not_called()
    refresh.assert_not_called()


def test_refresh_bead_wait_store_contains_refresh_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    refresh = MagicMock(side_effect=RuntimeError("integration failed"))
    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", refresh)

    refresh_bead_wait_store("proj")

    refresh.assert_called_once_with(beads_dir)
