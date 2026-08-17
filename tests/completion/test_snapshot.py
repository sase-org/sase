"""Tests for sase.completion.snapshot -- the checked-in drift gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.completion.snapshot import completion_spec_drift, current_structural_view

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_PATH = _REPO_ROOT / "tests" / "completion" / "snapshots" / "cli_spec.json"


def _load_snapshot() -> dict[str, Any]:
    return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_checked_in_snapshot_has_no_drift() -> None:
    drift = completion_spec_drift(_load_snapshot())
    assert drift is None, drift


def test_current_structural_view_matches_checked_in_snapshot() -> None:
    assert current_structural_view() == _load_snapshot()


def test_drift_message_names_the_regeneration_command() -> None:
    mutated = _load_snapshot()
    mutated["prog"] = "not-sase"

    message = completion_spec_drift(mutated)

    assert message is not None
    assert "just sync-completion-spec" in message


def test_missing_snapshot_reports_drift_and_names_regeneration_command() -> None:
    message = completion_spec_drift(None)

    assert message is not None
    assert "just sync-completion-spec" in message
