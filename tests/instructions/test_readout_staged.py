"""Staged-handoff readout tests (split from test_readout)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.instructions._readout_classify import classify_artifact_dir
from sase.instructions.readout import (
    ACCEPTED,
    MISS,
    MONITOR_PLAIN,
    MONITOR_PREPARED,
    PLAN_HANDOFF,
)
from tests.instructions._readout_support import (
    HANDOFF_PHASE,
    passthrough_manifest_normalize,
    write_done,
    write_meta,
)


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    passthrough_manifest_normalize(monkeypatch)


_STAGED_ID = "11111111-1111-1111-1111-111111111111"


def _write_staged_record(
    artifacts: Path,
    *,
    kind: str = "plan",
    dirty: tuple[str, ...] = (),
    payload: dict[str, object] | None = None,
    staged_id: str = _STAGED_ID,
) -> None:
    """Write a staged-handoff record the way the staging handlers persist it."""
    record = {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": kind,
        "created_at": "2026-10-06T12:00:00Z",
        "payload": payload if payload is not None else {},
        "successor_workspace": "none" if kind == "plan" else "inherit",
        "carry_allowed": kind != "plan",
        "dirty_obligations_at_stage": list(dirty),
    }
    (artifacts / ".sase_handoff_staged.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


def _write_final_context(artifacts: Path, *, submission_required: bool = True) -> None:
    (artifacts / "final_context.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "submission_required": submission_required,
                "selected_instances": [],
                "context": {"requirements": []},
            }
        ),
        encoding="utf-8",
    )


def _write_intents(artifacts: Path) -> None:
    index = artifacts / "continuation" / "completion_intents" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        json.dumps({"intents": {"intent-1": {"filename": "intent-1.json"}}}),
        encoding="utf-8",
    )


def test_staged_plan_with_dirty_missing_declaration_is_miss(tmp_path: Path) -> None:
    """A held staged handoff with a missing required declaration is a miss.

    There is no adopted handoff lifecycle entry here: the staged record
    alone establishes the handoff, and the dirty stage snapshot plus a
    requiring final context make the missing declaration a miss.
    """
    artifacts = tmp_path / "held-staged"
    artifacts.mkdir()
    write_meta(artifacts, name="held", provider="codex")
    write_done(artifacts)
    _write_staged_record(artifacts, kind="plan", dirty=("repo:main",))
    _write_final_context(artifacts, submission_required=True)
    assert classify_artifact_dir(artifacts) == MISS


def test_staged_plan_clean_missing_declaration_keeps_class(tmp_path: Path) -> None:
    """A clean staged handoff without a declaration keeps its class.

    The host can complete a clean handoff without a model-submitted
    declaration, so a missing declaration is not a miss here.
    """
    artifacts = tmp_path / "clean-staged"
    artifacts.mkdir()
    write_meta(artifacts, name="clean", provider="codex")
    write_done(artifacts)
    _write_staged_record(artifacts, kind="plan", dirty=())
    assert classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_staged_handoff_beats_accepted_submission(tmp_path: Path) -> None:
    """A recognized handoff keeps its class even with an accepted declaration."""
    artifacts = tmp_path / "staged-accepted"
    artifacts.mkdir()
    write_meta(artifacts, name="acc", provider="codex")
    write_done(artifacts)
    _write_staged_record(artifacts, kind="plan", dirty=())
    (artifacts / "final_submission.json").write_text(
        json.dumps({"accepted_at": "2026-10-06T12:00:00Z"}), encoding="utf-8"
    )
    assert classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_staged_not_required_keeps_handoff_class(tmp_path: Path) -> None:
    """An explicitly not-required declaration keeps the staged handoff class."""
    artifacts = tmp_path / "staged-notreq"
    artifacts.mkdir()
    write_meta(artifacts, name="nr", provider="codex")
    write_done(artifacts)
    _write_staged_record(artifacts, kind="monitor", dirty=())
    _write_final_context(artifacts, submission_required=False)
    assert classify_artifact_dir(artifacts) == MONITOR_PLAIN


def test_staged_prepared_monitor_needs_validated_intent(tmp_path: Path) -> None:
    """A staged prepared ref alone is a plain monitor without stored intents."""
    prepared = tmp_path / "staged-prepared"
    prepared.mkdir()
    write_meta(prepared, name="prep", provider="codex")
    write_done(prepared)
    _write_staged_record(
        prepared,
        kind="monitor",
        dirty=(),
        payload={"prepared_intent_ref": "intent-1"},
    )
    _write_intents(prepared)
    assert classify_artifact_dir(prepared) == MONITOR_PREPARED

    unvalidated = tmp_path / "staged-unvalidated"
    unvalidated.mkdir()
    write_meta(unvalidated, name="unval", provider="codex")
    write_done(unvalidated)
    _write_staged_record(
        unvalidated,
        kind="monitor",
        dirty=(),
        payload={"prepared_intent_ref": "intent-1"},
    )
    assert classify_artifact_dir(unvalidated) == MONITOR_PLAIN


def test_legacy_killed_handoff_preserved_with_required_declaration(
    tmp_path: Path,
) -> None:
    """Old kill-protocol handoffs are not rescored as missing declarations."""
    artifacts = tmp_path / "killed"
    artifacts.mkdir()
    write_meta(
        artifacts,
        name="old",
        provider="codex",
        extra={**HANDOFF_PHASE, "handoff_protocol": "killed"},
    )
    write_done(artifacts)
    (artifacts / "plan_path.json").write_text(
        json.dumps({"plan_path": "/tmp/plan.md"}), encoding="utf-8"
    )
    _write_final_context(artifacts, submission_required=True)
    assert classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_plan_validate_alone_is_not_handoff(tmp_path: Path) -> None:
    """A mere plan validation never establishes a handoff."""
    artifacts = tmp_path / "validate-only"
    artifacts.mkdir()
    write_meta(artifacts, name="val", provider="codex")
    write_done(artifacts)
    (artifacts / "tool_calls.jsonl").write_text(
        "sase plan validate\n", encoding="utf-8"
    )
    _write_final_context(artifacts, submission_required=True)
    assert classify_artifact_dir(artifacts) == MISS


def test_help_invocations_are_not_handoffs(tmp_path: Path) -> None:
    """Help output for staging commands never establishes a handoff."""
    artifacts = tmp_path / "help-only"
    artifacts.mkdir()
    write_meta(artifacts, name="help", provider="codex")
    write_done(artifacts)
    (artifacts / "tool_calls.jsonl").write_text(
        "sase plan propose -h\nsase monitor start --help\n", encoding="utf-8"
    )
    _write_final_context(artifacts, submission_required=True)
    assert classify_artifact_dir(artifacts) == MISS


def test_aborted_with_accepted_submission_is_accepted(tmp_path: Path) -> None:
    """An aborted handoff with an accepted declaration stays accepted."""
    artifacts = tmp_path / "aborted-accepted"
    artifacts.mkdir()
    write_meta(artifacts, name="aborted", provider="grok")
    write_done(artifacts)
    (artifacts / "handoff_aborted.json").write_text("{}", encoding="utf-8")
    (artifacts / "final_submission.json").write_text(
        json.dumps({"accepted_at": "2026-10-06T12:00:00Z"}), encoding="utf-8"
    )
    assert classify_artifact_dir(artifacts) == ACCEPTED
