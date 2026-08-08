"""Canonical BeadSnooze gate spec, notification, and preview rendering."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sase.bead.model import IssueType, Status, TaskPlusOneEvidence
from sase.bead.project import BeadProject
from sase.bead.snooze_gate import (
    BEAD_SNOOZE_PREVIEW_PATH,
    bead_snooze_presentation_note,
    create_bead_snooze_gate,
    render_bead_snooze_preview,
)
from sase.notification_gates.registry import adapter_for_kind
from sase.notifications import pending_actions
from sase.notifications.priority import is_priority
from sase.notifications.store import load_notifications
from tests.test_bead.snooze_gate_test_helpers import WAKE_TIME, snooze_record


def test_bead_snooze_gate_builds_canonical_spec_and_snoozed_notification(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_bead_snooze_gate(
        request_id="bead-snooze-canonical",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        snooze=snooze_record(plus_one_target=2, plus_one_baseline=0),
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
        ("snooze", "optional"),
    ]
    # The wake time is a declared input rather than a convention the reviewer
    # has to know about the free-text note.
    snooze_option = request["options"][2]
    assert len(snooze_option["inputs"]) == 1
    [duration_field] = snooze_option["inputs"]
    assert duration_field["id"] == "duration"
    assert duration_field["label"] == "Wake time"
    assert duration_field["type"] == "line"
    assert duration_field["required"] is True
    assert duration_field["default"] is None
    assert duration_field["choices"] == []
    assert "3d +2" in duration_field["placeholder"]
    input_schema = snooze_option["input_schema"]
    assert input_schema["required"] == ["duration"]
    assert set(input_schema["properties"]) == {"duration", "feedback"}
    assert "enum" not in input_schema["properties"]["duration"]
    assert "custom_duration" not in input_schema["properties"]
    assert input_schema["additionalProperties"] is False
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["panel_icon"] == "◈"
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
    assert notification.action_data["panel_icon"] == "◈"
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
        snooze=snooze_record(reason=""),
    )

    assert "+1 target" not in preview
    assert "Reason" not in preview


def test_bead_snooze_preview_omits_blank_notes_section() -> None:
    preview = render_bead_snooze_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="",
        snooze=snooze_record(),
    )

    assert preview.startswith("> [!NOTE] **◈ Snoozed by")
    assert "## Notes" not in preview
    assert "_No notes._" not in preview
    assert preview.endswith("## Description\n\nMake invalidation deterministic.\n")


def test_bead_snooze_gate_preview_carries_the_real_snooze_note(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as proj:
        task = proj.create("Follow up on the cache", IssueType.TASK, size="small")
        proj.update(task.id, status=Status.READY.value)
        issue = proj.snooze(
            task.id,
            until=WAKE_TIME,
            actor="bryanbugyi34@gmail.com",
            plus_ones=2,
            reason="waiting on the upstream fix",
        )
    assert issue.snooze is not None

    gate = create_bead_snooze_gate(
        request_id="bead-snooze-real-notes",
        bead_id=issue.id,
        project="sase",
        title=issue.title,
        snooze=issue.snooze,
        notes=issue.notes,
        created_by=issue.created_by,
        created_at=issue.created_at,
    )

    preview = (gate.bundle_path / BEAD_SNOOZE_PREVIEW_PATH).read_text(encoding="utf-8")
    # This is the payoff path: the wake reviewer sees the deferral's
    # conditions and reason at the moment they choose Close / Ready / Snooze
    # again, not just the raw wake time in the snooze block above it.
    assert "## Notes" in preview
    assert f"Snoozed until {WAKE_TIME}" in preview
    assert "Also wakes at 2 more +1s." in preview
    assert "Reason: waiting on the upstream fix" in preview


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
        snooze=snooze_record(),
        plus_one_evidence=(evidence,),
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["payload"]["plus_one_count"] == 1
    preview = (gate.bundle_path / BEAD_SNOOZE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "## +1 Evidence" in preview
    assert "Reproduced after clearing the cache." in preview
