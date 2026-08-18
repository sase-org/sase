"""Trusted TaskTriage gate construction, presentation, and notification coverage."""

from __future__ import annotations

import json
from pathlib import Path

from sase.bead.model import CloseRecord, ReopenCause, Resolution, TaskPlusOneEvidence
from sase.bead.task_gate import (
    TASK_TRIAGE_PREVIEW_PATH,
    create_task_triage_gate,
)
from sase.notification_gates.registry import adapter_for_kind
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications


def test_task_triage_gate_builds_canonical_spec_preview_and_pending_action(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="task-triage-canonical",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "task_triage"
    assert request["query"] == "launch OR close OR snooze"
    assert request["branches"] == [["launch"], ["close"], ["snooze"]]
    assert request["primary_branch"] == ["launch"]
    assert request["payload"] == {
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "created_at": "2026-01-01T00:00:00Z",
        "size": None,
        "refs": [],
        "plus_one_count": 0,
        "task_type": "",
        "task_type_fields": {},
        "plus_one_evidence": [],
        "close_history": [],
    }
    assert [(option["id"], option["feedback"]) for option in request["options"]] == [
        ("launch", "optional"),
        ("close", "required"),
        ("snooze", "optional"),
    ]
    # The wake time is a declared input rather than a convention the reviewer
    # has to know about the free-text note.
    snooze_option = request["options"][2]
    assert snooze_option["label"] == "Snooze"
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
    assert request["presentation"]["sender"] == "bead"
    assert request["presentation"]["notes"] == [
        "sase-task.1 — Follow up on the cache · ⧖ 2025-12-31"
    ]
    assert request["presentation"]["tags"] == ["bead", "task"]
    assert "chip" not in request["presentation"]
    assert "task_type_display" not in request["payload"]
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["panel_icon"] == "◈"
    assert request["presentation"]["origin_agent"] == "claude_coder"
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "# sase-task.1 — Follow up on the cache" in preview
    assert "**Filed by:** `@claude_coder`" in preview
    assert "**Created:** 2025-12-31 19:00:00 EST" in preview
    assert " ago" not in preview
    assert "Make invalidation deterministic." in preview
    assert "Discovered while landing sase-bg." in preview

    [notification] = load_notifications()
    assert notification.action == "TaskTriage"
    assert notification.sender == "bead"
    assert notification.icon == "✦"
    assert notification.tags == ["bead", "task"]
    assert notification.notes == ["sase-task.1 — Follow up on the cache · ⧖ 2025-12-31"]
    assert notification.action_data["panel"] == "beads"
    assert notification.action_data["panel_icon"] == "◈"
    assert notification.action_data["origin_agent"] == "claude_coder"
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "task_triage"
    assert adapter_for_kind("task_triage").auto_policy == "forbidden"


def test_task_triage_presents_structured_plus_one_evidence(gate_home: Path) -> None:
    del gate_home
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Reproduced after clearing the cache.",
        refs=("research:202608/cache.md",),
    )

    gate = create_task_triage_gate(
        request_id="task-triage-plus-one",
        bead_id="sase-task.2",
        project="sase",
        title="Cache remains stale",
        size="medium",
        refs=("research:202608/cache.md",),
        plus_one_evidence=(evidence,),
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["payload"]["plus_one_count"] == 1
    assert request["payload"]["plus_one_evidence"] == [
        {
            "timestamp": evidence.timestamp,
            "reporter": evidence.reporter,
            "note": evidence.note,
            "refs": list(evidence.refs),
        }
    ]
    assert request["presentation"]["notes"] == [
        "sase-task.2 [+1] — Cache remains stale"
    ]
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "**Size:** `medium`" in preview
    assert "## +1 Evidence" in preview
    assert "+1 agent.beta · 2026-08-01T15:00:00Z" in preview
    assert "Reproduced after clearing the cache." in preview


def test_task_triage_preview_shows_task_type_and_field_values(gate_home: Path) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="task-triage-typed",
        bead_id="sase-task.3",
        project="sase",
        title="Ctrl+] hint is wrong",
        description="Found while landing sase-ace.",
        task_type="bug",
        task_type_fields={
            "location": "src/sase/ace/help.py",
            "repro": "Open ACE, press Ctrl+].",
            "impact": "Confuses new users.",
        },
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["payload"]["task_type"] == "bug"
    assert request["payload"]["task_type_fields"] == {
        "location": "src/sase/ace/help.py",
        "repro": "Open ACE, press Ctrl+].",
        "impact": "Confuses new users.",
    }
    assert request["payload"]["task_type_display"] == {
        "glyph": "⨯",
        "name": "Bug",
        "accent_color": "#FF5F5F",
        "facts": [
            ["Location", "src/sase/ace/help.py"],
            ["Repro", "Open ACE, press Ctrl+]."],
        ],
    }
    assert request["presentation"]["chip"] == {
        "glyph": "⨯",
        "label": "bug",
        "color": "#FF5F5F",
    }
    assert request["presentation"]["notes"] == [
        "sase-task.3 — Ctrl+] hint is wrong",
        "Bug · Location: src/sase/ace/help.py · Repro: Open ACE, press Ctrl+].",
    ]
    assert request["presentation"]["tags"] == ["bead", "task", "bug"]
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "**Task type:** ⨯ `bug`" in preview
    assert preview.index("**Task type:**") < preview.index("## Description")
    assert "## Bug" in preview
    assert "**Location:** `src/sase/ace/help.py`" in preview
    assert "Open ACE, press Ctrl+]." in preview
    assert "Confuses new users." in preview
    [notification] = load_notifications()
    assert notification.tags == ["bead", "task", "bug"]
    assert notification.notes[1].startswith("Bug · Location:")
    assert notification.action_data["gate_chip_glyph"] == "⨯"
    assert notification.action_data["gate_chip_label"] == "bug"
    assert notification.action_data["gate_chip_color"] == "#FF5F5F"


def test_task_triage_presents_prior_close_history(gate_home: Path) -> None:
    del gate_home
    older = CloseRecord(
        closed_at="2026-06-01T00:00:00Z",
        reopened_at="2026-06-15T00:00:00Z",
        reopened_via=ReopenCause.OPEN,
        close_reason="Won't fix.",
        resolution=Resolution.CANCELED,
    )
    newer = CloseRecord(
        closed_at="2026-07-30T09:12:04Z",
        reopened_at="2026-08-05T17:04:11Z",
        reopened_via=ReopenCause.PLUS_ONE,
        close_reason="Not reproducible on main; the retry shim already covers this.",
        resolution=Resolution.CANCELED,
        reopened_by="claude.probe",
    )
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-05T17:04:11Z",
        reporter="claude.probe",
        note="Saw the same flake in CI run 4821 with a clean worktree.",
    )

    gate = create_task_triage_gate(
        request_id="task-triage-close-history",
        bead_id="sase-task.3",
        project="sase",
        title="Flaky retry test in CI",
        plus_one_evidence=(evidence,),
        close_history=(older, newer),
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["payload"]["close_history"] == [
        {
            "closed_at": "2026-06-01T00:00:00Z",
            "close_reason": "Won't fix.",
            "resolution": "canceled",
            "reopened_at": "2026-06-15T00:00:00Z",
            "reopened_via": "open",
            "reopened_by": None,
        },
        {
            "closed_at": "2026-07-30T09:12:04Z",
            "close_reason": (
                "Not reproducible on main; the retry shim already covers this."
            ),
            "resolution": "canceled",
            "reopened_at": "2026-08-05T17:04:11Z",
            "reopened_via": "plus_one",
            "reopened_by": "claude.probe",
        },
    ]
    assert request["presentation"]["notes"] == [
        "sase-task.3 [+1] [↺2] — Flaky retry test in CI"
    ]

    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    description_index = preview.index("## Description")
    newer_index = preview.index("Previously closed 2026-07-30T09:12:04Z as canceled")
    older_index = preview.index("Previously closed 2026-06-01T00:00:00Z as canceled")
    assert newer_index < older_index < description_index
    assert "Reopened 2026-08-05T17:04:11Z by a +1 from `@claude.probe`." in preview
    assert "Reopened 2026-06-15T00:00:00Z by `sase bead open`." in preview
    assert "+1 claude.probe · 2026-08-05T17:04:11Z ↺ reopened this task" in preview


def test_task_triage_gate_omits_blank_origin_agent(gate_home: Path) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="task-triage-without-filer",
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        created_by="  ",
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert "origin_agent" not in request["presentation"]
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "Filed by" not in preview
    [notification] = load_notifications()
    assert "origin_agent" not in notification.action_data


def test_task_triage_unresolved_type_degrades_honestly(gate_home: Path) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="task-triage-unknown-type",
        bead_id="sase-task.4",
        project="sase",
        title="Plugin type after uninstall",
        task_type="ghost-type",
        task_type_fields={"k": "v"},
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["payload"]["task_type_display"] == {
        "glyph": "?",
        "name": "ghost-type",
        "accent_color": "#6C6C6C",
        "facts": [["k", "v"]],
    }
    assert request["presentation"]["chip"] == {
        "glyph": "?",
        "label": "ghost-type",
        "color": "#6C6C6C",
    }
    assert request["presentation"]["notes"][1] == "ghost-type · k: v"
    assert request["presentation"]["tags"] == ["bead", "task", "ghost-type"]
    preview = (gate.bundle_path / TASK_TRIAGE_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "**Task type:** ? `ghost-type`" in preview
