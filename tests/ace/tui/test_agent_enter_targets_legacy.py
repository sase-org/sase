"""Legacy, remote, label, and index coverage for Enter-on-agent."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.tui.actions.agents._agent_enter_targets import (
    build_gate_notification_index,
    gate_target_label,
)

from ._agent_enter_targets_helpers import (
    _matching_action_data,
    _notification,
    _remote_agent,
    _resolve,
    _sources,
)
from ._agent_unread_helpers import make_agent


def test_standalone_waiting_input_gets_hitl_target() -> None:
    agent = make_agent(name="wf", status="WAITING INPUT", raw_suffix="20260918010101")
    resolution = _resolve(agent)
    assert _sources(resolution) == ["workflow_hitl", "patch"]
    [hitl, _] = resolution.targets
    assert hitl.label == "Respond to checkpoint"
    assert hitl.key.startswith("hitl:workflow:")


def test_standalone_question_gets_marker_target() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    resolution = _resolve(agent)
    assert _sources(resolution) == ["question_marker", "patch"]
    [marker, _] = resolution.targets
    assert marker.label == "Answer question"


def test_gate_target_suppresses_question_marker() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    notification = _notification(
        "n-q",
        "UserQuestion",
        action_data=_matching_action_data(agent),
    )
    resolution = _resolve(agent, [notification])
    assert _sources(resolution) == ["notification", "patch"]


def test_workflow_step_hitl_scope() -> None:
    agent = replace(
        make_agent(name="step", status="WAITING INPUT", raw_suffix="20260918010101"),
        parent_workflow="wf-name",
    )
    resolution = _resolve(agent)
    assert _sources(resolution) == ["workflow_hitl", "patch"]


def test_remote_attention_scope() -> None:
    resolution = _resolve(_remote_agent(pending=True))
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.source == "remote_attention"
    assert target.label == "Answer remote request"
    assert target.detail == "Help?"


def test_remote_without_attention_has_no_targets() -> None:
    assert _resolve(_remote_agent(pending=False)).targets == ()


@pytest.mark.parametrize(
    ("kind", "pending_status", "fallback", "expected"),
    [
        ("plan", "TALE", None, "Review tale plan"),
        ("plan", "tale", None, "Review tale plan"),
        ("plan", "PLAN", None, "Review plan"),
        ("epic_plan", "EPIC", None, "Review epic plan"),
        ("question", None, None, "Answer question"),
        ("sudo", "SUDO", None, "Review sudo request"),
        ("launch", None, None, "Approve agent launch"),
        ("hitl", None, None, "Respond to checkpoint"),
        ("task_triage", None, None, "Triage task"),
        ("bead_snooze", None, None, "Review snoozed bead"),
        ("flag_triage", None, None, "Triage flag"),
        ("bead_stale_cleanup", None, None, "Clean up stale beads"),
        ("plugins_required", None, None, "Install required plugins"),
        ("custom", None, "Do the thing", "Do the thing"),
        ("custom", None, None, "Open gate"),
        (None, None, None, "Open gate"),
        ("mystery", None, None, "Open gate"),
    ],
)
def test_gate_target_label_table(
    kind: str | None, pending_status: str | None, fallback: str | None, expected: str
) -> None:
    assert (
        gate_target_label(
            kind=kind, pending_status=pending_status, fallback_label=fallback
        )
        == expected
    )


def test_gate_notification_index_prefilters_and_caches() -> None:
    gate = _notification(
        "n-gate",
        "SudoRequest",
        action_data={"bundle_path": "/tmp/b/1", "raw_suffix": "20260918010101"},
    )
    plain = _notification("n-plain", "JumpToPatch")
    snapshot = [gate, plain]
    first = build_gate_notification_index(snapshot)
    assert build_gate_notification_index(snapshot) is first
    assert first.by_id["n-gate"] is gate
    assert first.by_bundle_path["/tmp/b/1"] is gate
    assert first.by_raw_suffix["20260918010101"] == [gate]
    assert [n.id for n in first.gate_notifications] == ["n-gate"]
    second = build_gate_notification_index([gate])
    assert second is not first
