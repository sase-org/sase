"""Readout classification tests (split from test_readout)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.instructions._readout_classify import classify_artifact_dir
from sase.instructions.readout import (
    MISS,
    MONITOR_PLAIN,
    MONITOR_PREPARED,
    NOT_REQUIRED,
    OTHER_HANDOFF,
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


def test_classify_handoff_beats_accepted_submission(tmp_path: Path) -> None:
    """A recognized handoff keeps its class despite an accepted submission."""
    artifacts = tmp_path / "accepted"
    artifacts.mkdir()
    write_meta(artifacts, name="acc", provider="codex")
    write_done(artifacts)
    (artifacts / "final_submission.json").write_text(
        json.dumps({"accepted_at": "2026-10-06T12:00:00Z"}), encoding="utf-8"
    )
    (artifacts / "tool_calls.jsonl").write_text(
        "sase monitor start -p verify -- just check\n", encoding="utf-8"
    )
    assert classify_artifact_dir(artifacts) == MONITOR_PLAIN


def test_classify_plan_handoff(tmp_path: Path) -> None:
    """``sase plan propose`` is a plan handoff."""
    artifacts = tmp_path / "plan-propose"
    artifacts.mkdir()
    write_meta(artifacts, name="pln", provider="muse")
    write_done(artifacts)
    (artifacts / "tool_calls.jsonl").write_text("sase plan propose\n", encoding="utf-8")
    assert classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_classify_monitor_prepared_needs_real_prepare(tmp_path: Path) -> None:
    """A prepared monitor needs a real prepare before the monitor start.

    A naive ``has final_submission.json`` check misses this case entirely:
    there is no submission, yet the run handed off through a prepared
    declaration. A bare ``-h`` help call never counts as the prepare.
    """
    artifacts = tmp_path / "prepared"
    artifacts.mkdir()
    write_meta(artifacts, name="mon", provider="codex")
    write_done(artifacts)
    (artifacts / "tool_calls.jsonl").write_text(
        "sase final prepare /tmp/wrapper.json -j\n"
        "sase monitor start -p verify -- just check\n",
        encoding="utf-8",
    )
    assert classify_artifact_dir(artifacts) == MONITOR_PREPARED

    help_only = tmp_path / "help-only"
    help_only.mkdir()
    write_meta(help_only, name="mon2", provider="codex")
    write_done(help_only)
    (help_only / "tool_calls.jsonl").write_text(
        "sase final prepare -h\nsase monitor start -p verify -- just check\n",
        encoding="utf-8",
    )
    assert classify_artifact_dir(help_only) == MONITOR_PLAIN


def test_classify_other_handoff(tmp_path: Path) -> None:
    """Pipe, questions, and handoff count as other recognized handoffs."""
    for marker in ("sase pipe", "sase questions", "sase handoff"):
        artifacts = tmp_path / f"other-{marker.split()[-1]}"
        artifacts.mkdir()
        write_meta(artifacts, name="oth", provider="grok")
        write_done(artifacts)
        (artifacts / "tool_calls.jsonl").write_text(f"{marker} ...\n", encoding="utf-8")
        assert classify_artifact_dir(artifacts) == OTHER_HANDOFF


def test_classify_not_required(tmp_path: Path) -> None:
    """``submission_required: false`` in final_context means not required."""
    artifacts = tmp_path / "notreq"
    artifacts.mkdir()
    write_meta(artifacts, name="nr", provider="claude")
    write_done(artifacts)
    (artifacts / "final_context.json").write_text(
        json.dumps({"submission_required": False}), encoding="utf-8"
    )
    (artifacts / "tool_calls.jsonl").write_text("", encoding="utf-8")
    assert classify_artifact_dir(artifacts) == NOT_REQUIRED


def test_classify_host_monitor_plain_without_tool_calls(tmp_path: Path) -> None:
    """A lifecycle handoff plus ``monitor_id`` is a plain monitor handoff."""
    artifacts = tmp_path / "host-mon"
    artifacts.mkdir()
    write_meta(
        artifacts,
        name="10f--code",
        provider="grok",
        extra={
            **HANDOFF_PHASE,
            "monitor_id": "9m6zn3csd5wf",
            "monitor_member_agent_name": "10f--mon",
        },
    )
    write_done(artifacts)
    assert classify_artifact_dir(artifacts) == MONITOR_PLAIN


def test_classify_host_monitor_prepared_from_intents(tmp_path: Path) -> None:
    """Prepared monitor uses ``completion_intents/index.json`` intents."""
    artifacts = tmp_path / "host-prep"
    artifacts.mkdir()
    write_meta(
        artifacts,
        name="prep",
        provider="codex",
        extra={**HANDOFF_PHASE, "monitor_id": "monid"},
    )
    write_done(artifacts)
    index = artifacts / "continuation" / "completion_intents" / "index.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({"intents": {"intent-1": {"filename": "intent-1.json"}}}),
        encoding="utf-8",
    )
    assert classify_artifact_dir(artifacts) == MONITOR_PREPARED


def test_classify_host_plan_handoff(tmp_path: Path) -> None:
    """``plan_path.json`` with a handoff phase is a plan handoff."""
    artifacts = tmp_path / "host-plan"
    artifacts.mkdir()
    write_meta(artifacts, name="pln", provider="muse", extra=HANDOFF_PHASE)
    write_done(artifacts)
    (artifacts / "plan_path.json").write_text(
        json.dumps({"plan_path": "/tmp/plan.md"}), encoding="utf-8"
    )
    assert classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_classify_host_other_handoff(tmp_path: Path) -> None:
    """A handoff phase with no plan or monitor markers is other."""
    artifacts = tmp_path / "host-other"
    artifacts.mkdir()
    write_meta(artifacts, name="oth", provider="grok", extra=HANDOFF_PHASE)
    write_done(artifacts)
    assert classify_artifact_dir(artifacts) == OTHER_HANDOFF


def test_classify_aborted_handoff_is_miss(tmp_path: Path) -> None:
    """``handoff_aborted.json`` is never a handoff, even with a handoff phase."""
    artifacts = tmp_path / "aborted"
    artifacts.mkdir()
    write_meta(
        artifacts,
        name="aborted",
        provider="grok",
        extra={**HANDOFF_PHASE, "monitor_id": "monid"},
    )
    write_done(artifacts)
    (artifacts / "handoff_aborted.json").write_text("{}", encoding="utf-8")
    (artifacts / "tool_calls.jsonl").write_text(
        "sase monitor start -p verify -- just check\n", encoding="utf-8"
    )
    assert classify_artifact_dir(artifacts) == MISS


def test_classify_host_handoff_beats_accepted(tmp_path: Path) -> None:
    """Host handoff facts keep their class despite an accepted submission."""
    artifacts = tmp_path / "accepted-host"
    artifacts.mkdir()
    write_meta(
        artifacts,
        name="acc",
        provider="codex",
        extra={**HANDOFF_PHASE, "monitor_id": "monid"},
    )
    write_done(artifacts)
    (artifacts / "final_submission.json").write_text(
        json.dumps({"accepted_at": "2026-10-06T12:00:00Z"}), encoding="utf-8"
    )
    (artifacts / "plan_path.json").write_text("{}", encoding="utf-8")
    assert classify_artifact_dir(artifacts) == PLAN_HANDOFF


def test_classify_miss(tmp_path: Path) -> None:
    """No declaration, handoff, or waiver is a miss."""
    artifacts = tmp_path / "miss"
    artifacts.mkdir()
    write_meta(artifacts, name="ms", provider="claude")
    write_done(artifacts)
    (artifacts / "final_context.json").write_text(
        json.dumps({"submission_required": True}), encoding="utf-8"
    )
    (artifacts / "tool_calls.jsonl").write_text("sase bead read\n", encoding="utf-8")
    assert classify_artifact_dir(artifacts) == MISS
