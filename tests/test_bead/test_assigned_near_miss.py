"""Unit coverage for one-segment assigned-bead near-miss detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.assigned_near_miss import (
    _assigned_bead_id,
    _near_miss_of_assigned,
    annotate_not_found_message,
)
from sase.bead.work_types import SASE_BEAD_ID_ENV, SASE_PHASE_BEAD_ID_ENV

_ASSIGNED = "bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.6.6.1"
_REQUESTED = "bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.6.1"


@pytest.mark.parametrize(
    ("requested", "assigned", "expected"),
    [
        (_REQUESTED, _ASSIGNED, True),
        (_ASSIGNED, _REQUESTED, True),
        ("bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.6.6.2", _ASSIGNED, False),
        ("bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.6.6", _ASSIGNED, False),
        (f"{_ASSIGNED}.9", _ASSIGNED, False),
        ("bob-cli-cj.6.6.6.5.6.5.5.6.6.6.6.6.6.1", _ASSIGNED, False),
        ("bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.1", _ASSIGNED, False),
        (_ASSIGNED, _ASSIGNED, False),
        ("sase-1ok", "sase-1ok.3", False),
        ("sase-xx.1.1", "sase-xx.1.2.1", True),
        ("sase-xx.2.1", "sase-xx.1.2.1", True),
        ("sase-xx.1.2.2", "sase-xx.1.2.1", False),
        ("", _ASSIGNED, False),
        (_ASSIGNED, "", False),
    ],
)
def test_near_miss_of_assigned(requested: str, assigned: str, expected: bool) -> None:
    assert _near_miss_of_assigned(requested, assigned) is expected


def test_assigned_bead_id_prefers_phase_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SASE_PHASE_BEAD_ID_ENV, "phase-1")
    monkeypatch.setenv(SASE_BEAD_ID_ENV, "bead-1")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    assert _assigned_bead_id() == "phase-1"


def test_assigned_bead_id_falls_back_to_bead_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.setenv(SASE_BEAD_ID_ENV, "bead-1")
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    assert _assigned_bead_id() == "bead-1"


def test_assigned_bead_id_reads_agent_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"phase_bead_id": "meta-phase", "bead_id": "meta-bead"}),
        encoding="utf-8",
    )
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv(SASE_BEAD_ID_ENV, raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    assert _assigned_bead_id() == "meta-phase"


def test_assigned_bead_id_meta_bead_id_when_phase_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"bead_id": "meta-bead"}),
        encoding="utf-8",
    )
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv(SASE_BEAD_ID_ENV, raising=False)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    assert _assigned_bead_id() == "meta-bead"


def test_assigned_bead_id_none_outside_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv(SASE_BEAD_ID_ENV, raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    assert _assigned_bead_id() is None


def test_annotate_not_found_appends_did_you_mean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.setenv(SASE_BEAD_ID_ENV, _ASSIGNED)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    message = annotate_not_found_message(f"issue not found: {_REQUESTED}")
    assert message.endswith(f"(did you mean `{_ASSIGNED}`?)")


def test_annotate_not_found_skips_unrelated_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SASE_PHASE_BEAD_ID_ENV, raising=False)
    monkeypatch.setenv(SASE_BEAD_ID_ENV, _ASSIGNED)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    message = annotate_not_found_message("issue not found: beads-missing")
    assert message == "issue not found: beads-missing"
