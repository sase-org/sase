"""Archived aborted-handoff evidence readers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sase.agent.handoff_inflight import (
    HANDOFF_ABORTED_FILENAME,
    HANDOFF_INFLIGHT_MARKER,
    load_handoff_aborted_record,
    merge_handoff_aborted_into_done_marker,
)


def _write_aborted(tmp_path: Path, record: dict) -> dict:
    (tmp_path / HANDOFF_ABORTED_FILENAME).write_text(
        json.dumps(record), encoding="utf-8"
    )
    return record


def test_inflight_marker_name_is_stable() -> None:
    assert HANDOFF_INFLIGHT_MARKER == ".sase_handoff_inflight"


def test_load_missing_aborted_record_is_none(tmp_path: Path) -> None:
    assert load_handoff_aborted_record(str(tmp_path)) is None
    assert load_handoff_aborted_record(None) is None


def test_load_malformed_aborted_record_is_none(tmp_path: Path) -> None:
    (tmp_path / HANDOFF_ABORTED_FILENAME).write_text("not-json", encoding="utf-8")
    assert load_handoff_aborted_record(str(tmp_path)) is None


def test_merge_aborted_into_done_marker_being_built(tmp_path: Path) -> None:
    record = {"reason": "handoff_process_dead", "command": "sase monitor start"}
    _write_aborted(tmp_path, record)
    marker: dict = {"outcome": "completed"}
    assert merge_handoff_aborted_into_done_marker(str(tmp_path), marker) is marker
    assert marker["handoff_aborted"] == record


def test_merge_aborted_keeps_explicit_marker_value(tmp_path: Path) -> None:
    _write_aborted(tmp_path, {"reason": "handoff_process_dead"})
    marker: dict = {"handoff_aborted": {"reason": "explicit"}}
    merge_handoff_aborted_into_done_marker(str(tmp_path), marker)
    assert marker["handoff_aborted"] == {"reason": "explicit"}


def test_recovery_evidence_names_killed_handoff() -> None:
    from sase.finalizers.declaration_recovery_evidence import (
        build_recovery_evidence,
    )

    context = SimpleNamespace(context=SimpleNamespace(obligations=()))
    evidence = build_recovery_evidence(
        context=context,  # type: ignore[arg-type]
        original_prompt=None,
        response_text="",
        artifacts_dir=None,
        handoff_aborted={"command": "sase monitor start -- just check"},
    )
    assert "sase monitor start -- just check" in evidence
    assert "killed before the monitor started" in evidence
    assert "no follow-up agent will run" in evidence


def test_recovery_evidence_without_abort_has_no_handoff_section() -> None:
    from sase.finalizers.declaration_recovery_evidence import (
        build_recovery_evidence,
    )

    context = SimpleNamespace(context=SimpleNamespace(obligations=()))
    evidence = build_recovery_evidence(
        context=context,  # type: ignore[arg-type]
        original_prompt=None,
        response_text="",
        artifacts_dir=None,
    )
    assert "Handoff attempt" not in evidence
