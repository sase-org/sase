"""Unit tests for ``sase init --check --json`` payload parsing."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from sase.main.init_plan import INIT_CHECK_JSON_SCHEMA_VERSION
from sase.ace.tui.modals.projects_pane_init_payload import (
    InitCheckPayloadError,
    parse_init_check_payload,
)

from .projects_pane_init_test_helpers import (
    raw_action,
    raw_document,
    raw_planner,
    raw_project,
)


def test_parse_current_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 4, 12, 0, 0)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane_init_payload.local_now",
        lambda: now,
    )
    document = raw_document(
        raw_project("sase", display_name="SASE", status="current"),
        status="current",
    )

    payload = parse_init_check_payload(json.dumps(document))

    assert payload.schema_version == INIT_CHECK_JSON_SCHEMA_VERSION
    assert payload.status == "current"
    assert payload.planned_at == now
    project = payload.projects[0]
    assert project.name == "sase"
    assert project.display_name == "SASE"
    assert project.is_current
    assert not project.unavailable
    assert not project.held
    assert not project.changed_runnable
    assert [planner.label for planner in project.planners] == ["Config", "Memory"]


def test_parse_drifted_payload_is_distinct_from_blocked() -> None:
    drifted = raw_document(
        raw_project(
            "sase",
            status="needs_attention",
            planners=[
                raw_planner(
                    "memory",
                    summary="1 update",
                    has_changes=True,
                    actions=[raw_action()],
                )
            ],
        ),
        status="drift",
    )
    blocked = raw_document(
        raw_project(
            "sase",
            status="failed",
            planners=[
                raw_planner(
                    "memory",
                    summary="1 update",
                    has_changes=True,
                    runnable=False,
                    requires_tty=True,
                    blockers=["owner identity requires a TTY"],
                    actions=[raw_action()],
                )
            ],
        ),
        status="blocked",
    )

    drift_payload = parse_init_check_payload(json.dumps(drifted))
    blocked_payload = parse_init_check_payload(json.dumps(blocked))

    assert drift_payload.status == "drift"
    assert blocked_payload.status == "blocked"
    assert drift_payload.projects[0].changed_runnable
    assert not drift_payload.projects[0].held
    assert blocked_payload.projects[0].held
    assert blocked_payload.projects[0].requires_tty
    assert not blocked_payload.projects[0].changed_runnable


def test_parse_preserves_actions_truncated() -> None:
    document = raw_document(
        raw_project(
            "sase",
            status="needs_attention",
            planners=[
                raw_planner(
                    "memory",
                    has_changes=True,
                    actions=[raw_action()],
                    action_count=12,
                    actions_truncated=True,
                )
            ],
        ),
        status="drift",
    )

    payload = parse_init_check_payload(json.dumps(document))

    planner = payload.projects[0].planners[0]
    assert planner.actions_truncated is True
    assert planner.action_count == 12


def test_unavailable_project_is_classified_unavailable_not_just_failed() -> None:
    document = raw_document(
        raw_project(
            "missing",
            display_name="Missing",
            status="failed",
            unavailable_reason="primary workspace is unavailable: /gone",
            planners=[],
        ),
        status="blocked",
    )

    payload = parse_init_check_payload(json.dumps(document))
    project = payload.projects[0]

    assert project.status == "failed"
    assert project.unavailable is True
    assert project.is_current is False
    assert project.unavailable_reason == "primary workspace is unavailable: /gone"


def test_schema_version_mismatch_names_both_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane_init_payload.shutil.which",
        lambda _name: "/usr/bin/sase",
    )
    document = raw_document(raw_project(), schema_version=99)

    with pytest.raises(InitCheckPayloadError, match="schema_version 99") as exc_info:
        parse_init_check_payload(json.dumps(document))

    message = str(exc_info.value)
    assert str(INIT_CHECK_JSON_SCHEMA_VERSION) in message
    assert "/usr/bin/sase" in message
    assert "PATH" in message


def test_non_json_stdout_includes_captured_tail() -> None:
    stdout = "noise\n" * 12 + "error: no such project 'nope'\n"

    with pytest.raises(InitCheckPayloadError) as exc_info:
        parse_init_check_payload(stdout)

    message = str(exc_info.value)
    assert "no such project 'nope'" in message
    assert message.count("\n") <= 10


def test_json_slice_recovers_payload_with_stray_lines() -> None:
    document = raw_document(raw_project("sase"), status="current")
    stdout = "warning: stray\n" + json.dumps(document) + "\ntrailing\n"

    payload = parse_init_check_payload(stdout)

    assert payload.status == "current"
    assert payload.projects[0].name == "sase"
