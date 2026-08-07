"""Trusted BeadSnooze gate contract and host-side effect coverage."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from sase.bead.model import SnoozeRecord, TaskPlusOneEvidence
from sase.bead.snooze_time import (
    SnoozeTimeError,
    parse_snooze_request,
    parse_snooze_until,
)
from sase.bead.snooze_gate import (
    BEAD_SNOOZE_COMMAND_PATHS,
    BEAD_SNOOZE_PREVIEW_PATH,
    _build_bead_snooze_gate_spec,
    _bead_snooze_close_reason,
    bead_snooze_presentation_note,
    create_bead_snooze_gate,
    render_bead_snooze_preview,
    translate_bead_snooze_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.registry import adapter_for_kind
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.priority import is_priority
from sase.notifications.store import load_notifications
from tests.test_bead.conftest import FIXED_BEAD_NOW

WAKE_TIME = "2026-08-09T09:00:00-04:00"


def _snooze(**overrides: Any) -> SnoozeRecord:
    fields: dict[str, Any] = {
        "until": WAKE_TIME,
        "snoozed_at": "2026-08-06T09:00:00-04:00",
        "snoozed_by": "bryanbugyi34@gmail.com",
        "reason": "waiting on the upstream fix",
    }
    fields.update(overrides)
    return SnoozeRecord(**fields)


def _spec(*, request_id: str = "bead-snooze-1", **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "snooze": _snooze(),
        "description": "Make invalidation deterministic.",
        "notes": "Discovered while landing sase-bg.",
        "created_by": "claude_coder",
        "created_at": "2026-01-01T00:00:00Z",
        "producer": {"agent_name": "snooze-test"},
    }
    fields.update(overrides)
    return _build_bead_snooze_gate_spec(**fields)


def test_bead_snooze_gate_builds_canonical_spec_and_snoozed_notification(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_bead_snooze_gate(
        request_id="bead-snooze-canonical",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        snooze=_snooze(plus_one_target=2, plus_one_baseline=0),
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "bead_snooze"
    assert request["query"] == "close OR ready OR snooze"
    assert request["branches"] == [["close"], ["ready"], ["snooze"]]
    assert request["primary_branch"] == ["close"]
    assert request["payload"]["snooze"] == {
        "until": WAKE_TIME,
        "snoozed_at": "2026-08-06T09:00:00-04:00",
        "snoozed_by": "bryanbugyi34@gmail.com",
        "plus_one_target": 2,
        "plus_one_baseline": 0,
        "reason": "waiting on the upstream fix",
    }
    assert [(option["id"], option["feedback"]) for option in request["options"]] == [
        ("close", "optional"),
        ("ready", "optional"),
        ("snooze", "required"),
    ]
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["snooze_until"] == WAKE_TIME

    preview = (gate.bundle_path / BEAD_SNOOZE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert preview.startswith("> [!NOTE] **◈ Snoozed by `@bryanbugyi34@gmail.com`")
    assert "> **Wakes:** 2026-08-09 09:00:00 EDT" in preview
    assert "> **+1 target:** 2 more (2 total) wakes it early" in preview
    assert "> **Reason:** waiting on the upstream fix" in preview
    assert "# sase-task.1 — Follow up on the cache" in preview
    assert " ago" not in preview

    # D2: the gate is born snoozed, so no window exists in which the row is
    # briefly unread and no second timer is needed to wake it.
    [notification] = load_notifications()
    assert notification.action == "BeadSnooze"
    assert notification.muted is True
    assert notification.snooze_until == WAKE_TIME
    assert notification.icon == "◈"
    assert notification.action_data["panel"] == "beads"
    assert is_priority(notification)
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "bead_snooze"
    assert adapter_for_kind("bead_snooze").auto_policy == "forbidden"


def test_bead_snooze_presentation_note_is_clock_independent() -> None:
    def render(now: datetime) -> str:
        with patch("sase.core.time.local_now", return_value=now):
            return bead_snooze_presentation_note(
                "sase-task.1", "Follow up on the cache", 1, until=WAKE_TIME
            )

    tz = ZoneInfo("America/New_York")
    early = render(datetime(2026, 8, 6, 12, 0, tzinfo=tz))
    late = render(datetime(2027, 9, 9, 12, 0, tzinfo=tz))

    assert early == late
    assert early == (
        "sase-task.1 [+1] — Follow up on the cache · ◈ 2026-08-09 09:00:00 EDT"
    )


def test_bead_snooze_preview_omits_absent_optional_snooze_fields() -> None:
    preview = render_bead_snooze_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="",
        notes="",
        snooze=_snooze(reason=""),
    )

    assert "+1 target" not in preview
    assert "Reason" not in preview


def test_bead_snooze_gate_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = _spec(request_id="bead-snooze-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(query="ready OR close OR snooze"),
            "invalid_bead_snooze_query",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"].pop("snooze"),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"]["snooze"].update(until="not-a-timestamp"),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"]["snooze"].update(snoozed_by="  "),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["payload"]["snooze"].update(
                plus_one_target=1, plus_one_baseline=3
            ),
            "invalid_bead_snooze_payload",
        ),
        (
            lambda spec: spec["options"][2].update(feedback="optional"),
            "invalid_bead_snooze_options",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_bead_snooze_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {"path": "forged.txt", "role": "attachment", "content": "unexpected"}
            ),
            "invalid_bead_snooze_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(
                snooze_until="2026-08-10T09:00:00-04:00"
            ),
            "invalid_bead_snooze_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(
                snooze_until="2026-08-10T09:00:00"
            ),
            "invalid_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_bead_snooze_preview",
        ),
    ],
)
def test_bead_snooze_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_bead_snooze_close_uses_the_preset_reason_when_feedback_is_empty(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-close-preset"))
    project, mutation, mutation_scope = _mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
    ):
        execute_gate_selection(gate.bundle_path, ["close"], {}, source="tui")

    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason=_bead_snooze_close_reason(WAKE_TIME),
        resolution="canceled",
    )
    mutation.commit.assert_called_once_with("chore(beads): close sase-task.1")


def test_bead_snooze_close_feedback_replaces_the_preset_reason(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-close-override"))
    project, _mutation, mutation_scope = _mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
    ):
        execute_gate_selection(
            gate.bundle_path,
            ["close"],
            {},
            feedback="Fixed upstream.",
            source="mobile",
        )

    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason="Fixed upstream.",
        resolution="canceled",
    )


def test_bead_snooze_ready_cancels_the_snooze_and_notes_the_wake(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-ready"))
    project, mutation, mutation_scope = _mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        execute_gate_selection(gate.bundle_path, ["ready"], {}, source="tui")

    project.cancel_snooze.assert_called_once_with("sase-task.1", actor="owner@example")
    project.append_note.assert_called_once_with(
        "sase-task.1",
        "Woken from snooze and returned to triage.",
        author="owner@example",
    )
    mutation.commit.assert_called_once_with("chore(beads): wake sase-task.1")


def test_bead_snooze_resnooze_defers_again_with_the_typed_duration(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-again"))
    project, mutation, mutation_scope = _mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        execute_gate_selection(
            gate.bundle_path,
            ["snooze"],
            {},
            feedback="3d +2",
            source="tui",
        )

    [call] = project.snooze.call_args_list
    assert call.args == ("sase-task.1",)
    assert call.kwargs["plus_ones"] == 2
    assert call.kwargs["reason"] == "waiting on the upstream fix"
    assert call.kwargs["actor"] == "owner@example"
    resolved = datetime.fromisoformat(call.kwargs["until"])
    reference = FIXED_BEAD_NOW.replace(tzinfo=resolved.tzinfo)
    assert resolved == (reference + timedelta(days=3)).replace(microsecond=0)
    mutation.commit.assert_called_once_with("chore(beads): snooze sase-task.1")


def test_bead_snooze_rejects_an_unparsable_duration_and_leaves_the_gate_pending(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-typo"))

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(
            gate.bundle_path,
            ["snooze"],
            {},
            feedback="threeish days",
            source="tui",
        )

    assert exc_info.value.code == "invalid_snooze_duration"
    assert "accepted forms" in str(exc_info.value)
    assert not gate.response_path.exists()
    [notification] = load_notifications()
    assert notification.snooze_until == WAKE_TIME


def test_bead_snooze_translation_requires_a_matching_result(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-translate"))
    response = {
        "selected_option_ids": ["ready"],
        "option_results": [{"id": "ready", "result": {"action": "close"}}],
    }

    with pytest.raises(GateError) as exc_info:
        translate_bead_snooze_response(gate.bundle_path, response)

    assert exc_info.value.code == "invalid_response"


def test_bead_snooze_commands_reject_nonempty_input(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="bead-snooze-command-input"))
    command_path = gate.bundle_path / BEAD_SNOOZE_COMMAND_PATHS["snooze"]

    import subprocess

    completed = subprocess.run(
        [str(command_path)],
        cwd=gate.bundle_path,
        input=b'{"unexpected": true}\n',
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert b"must be empty" in completed.stderr


def test_bead_snooze_gate_carries_plus_one_evidence_like_task_triage(
    gate_home: Path,
) -> None:
    del gate_home
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Reproduced after clearing the cache.",
    )

    gate = create_bead_snooze_gate(
        request_id="bead-snooze-evidence",
        bead_id="sase-task.2",
        project="sase",
        title="Cache remains stale",
        snooze=_snooze(),
        plus_one_evidence=(evidence,),
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["payload"]["plus_one_count"] == 1
    preview = (gate.bundle_path / BEAD_SNOOZE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "## +1 Evidence" in preview
    assert "Reproduced after clearing the cache." in preview


@pytest.mark.parametrize(
    ("text", "expected_plus_ones"),
    [("3d", None), ("2h", None), ("1h30m", None), ("3d +2", 2), ("30m  +1", 1)],
)
def test_snooze_request_parses_every_accepted_form(
    text: str, expected_plus_ones: int | None
) -> None:
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    request = parse_snooze_request(text, now=now)

    assert request.plus_ones == expected_plus_ones
    assert datetime.fromisoformat(request.until) > now


def test_snooze_request_resolves_days_and_absolute_timestamps() -> None:
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    assert parse_snooze_until("3d", now=now) == (now + timedelta(days=3)).isoformat()
    assert (
        parse_snooze_until("1d2h", now=now)
        == (now + timedelta(days=1, hours=2)).isoformat()
    )
    assert parse_snooze_until(WAKE_TIME, now=now) == WAKE_TIME


def test_snooze_request_attaches_the_configured_timezone_to_a_naive_timestamp() -> None:
    """A naive ISO-8601 timestamp is read in the configured zone, not refused."""
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    request = parse_snooze_request("2026-08-09T09:00:00", now=now)

    assert request.until == WAKE_TIME


@pytest.mark.parametrize(
    "text",
    [
        "",
        "threeish days",
        "3 days",
        "0m",
        "2026-08-01T09:00:00-04:00",
        "3d +0",
        "3d ++2",
    ],
)
def test_snooze_request_rejects_unusable_input(text: str) -> None:
    now = datetime.fromisoformat("2026-08-06T09:00:00-04:00")

    with pytest.raises(SnoozeTimeError) as exc_info:
        parse_snooze_request(text, now=now)

    assert "accepted forms" in str(exc_info.value)


def _mutation_double() -> tuple[MagicMock, Any, Any]:
    """Return a bead-store mutation double and the scope that yields it."""
    project = MagicMock()
    project.owner = "owner@example"
    project.last_mutation_outcome = {
        "closed_ids": ["sase-task.1"],
        "already_closed_ids": [],
        "noted_ids": [],
        "cascade_closed_ids": [],
    }
    mutation = SimpleNamespace(project=project, commit=MagicMock())

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield mutation

    return project, mutation, mutation_scope


def test_snooze_request_matches_the_cli_seconds_resolution() -> None:
    """Every surface stores the same shape of wake instant, to the second."""
    now = datetime.fromisoformat("2026-08-06T09:00:00.123456-04:00")

    request = parse_snooze_request("2h", now=now)

    assert request.until == "2026-08-06T11:00:00-04:00"
