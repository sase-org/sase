"""Trusted TaskTriage gate contract and host-side effect coverage."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from sase.bead.model import CloseRecord, ReopenCause, Resolution, TaskPlusOneEvidence
from sase.bead.task_gate import (
    TASK_TRIAGE_COMMAND_PATHS,
    TASK_TRIAGE_PREVIEW_PATH,
    _build_task_triage_gate_spec,
    _resolve_task_triage_project_cwd,
    create_task_triage_gate,
    render_task_triage_preview,
    task_triage_presentation_note,
    translate_task_triage_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.registry import adapter_for_kind
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications


def _spec(*, request_id: str = "task-triage-1") -> dict[str, Any]:
    return _build_task_triage_gate_spec(
        request_id=request_id,
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
        producer={"agent_name": "triage-test"},
    )


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
    assert request["query"] == "launch OR close"
    assert request["branches"] == [["launch"], ["close"]]
    assert request["primary_branch"] == ["launch"]
    assert request["payload"] == {
        "bead_id": "sase-task.1",
        "project": "sase",
        "title": "Follow up on the cache",
        "created_at": "2026-01-01T00:00:00Z",
        "size": None,
        "refs": [],
        "plus_one_count": 0,
        "plus_one_evidence": [],
        "close_history": [],
    }
    assert [(option["id"], option["feedback"]) for option in request["options"]] == [
        ("launch", "optional"),
        ("close", "required"),
    ]
    assert request["presentation"]["sender"] == "bead"
    assert request["presentation"]["notes"] == [
        "sase-task.1 — Follow up on the cache · ⧖ 2025-12-31"
    ]
    assert request["presentation"]["tags"] == ["bead", "task"]
    assert request["presentation"]["panel"] == "beads"
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


def test_task_triage_close_history_placeholders_for_missing_fields() -> None:
    record = CloseRecord(
        closed_at="2026-06-01T00:00:00Z",
        reopened_at="2026-06-15T00:00:00Z",
        reopened_via=ReopenCause.UPDATE,
    )

    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="",
        notes="",
        close_history=(record,),
    )

    assert (
        "> [!WARNING] **↺ Previously closed 2026-06-01T00:00:00Z as "
        "(unrecorded)** (none)"
    ) in preview
    assert "Reopened 2026-06-15T00:00:00Z by a status update." in preview


def test_task_triage_presentation_note_includes_reopen_badge() -> None:
    note = task_triage_presentation_note(
        "sase-task.1", "Flaky retry test in CI", 1, reopen_count=2
    )

    assert note == "sase-task.1 [+1] [↺2] — Flaky retry test in CI"


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


def test_task_triage_created_rendering_is_absolute_and_clock_independent() -> None:
    """The persisted preview and note must not drift as the gate ages."""

    def render(now: datetime) -> tuple[str, str]:
        with patch("sase.core.time.local_now", return_value=now):
            return (
                render_task_triage_preview(
                    bead_id="sase-task.1",
                    title="Follow up on the cache",
                    description="Make invalidation deterministic.",
                    notes="",
                    created_by="claude_coder",
                    created_at="2026-01-01T00:00:00Z",
                ),
                task_triage_presentation_note(
                    "sase-task.1",
                    "Follow up on the cache",
                    0,
                    created_at="2026-01-01T00:00:00Z",
                ),
            )

    tz = ZoneInfo("America/New_York")
    early = render(datetime(2026, 1, 1, 12, 0, tzinfo=tz))
    late = render(datetime(2027, 9, 9, 12, 0, tzinfo=tz))

    assert early == late
    preview, note = early
    assert "**Created:** 2025-12-31 19:00:00 EST\n" in preview
    assert note == "sase-task.1 — Follow up on the cache · ⧖ 2025-12-31"


def test_task_triage_created_rendering_is_omitted_without_a_timestamp() -> None:
    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="",
        notes="",
    )

    assert "Created" not in preview
    assert (
        task_triage_presentation_note("sase-task.1", "Follow up on the cache", 0)
        == "sase-task.1 — Follow up on the cache"
    )


def test_task_triage_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = _spec(request_id="task-triage-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(query="close OR launch"),
            "invalid_task_triage_query",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(created_at=17),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(created_at="2020-06-01T00:00:00Z"),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["payload"].update(close_history=[{"bad": True}]),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                close_history=[
                    {
                        "closed_at": "2026-06-01T00:00:00Z",
                        "close_reason": None,
                        "resolution": None,
                        "reopened_at": "2026-06-15T00:00:00Z",
                        "reopened_via": "not_a_real_cause",
                        "reopened_by": None,
                    }
                ]
            ),
            "invalid_task_triage_payload",
        ),
        (
            lambda spec: spec["options"][0].update(feedback="disabled"),
            "invalid_task_triage_options",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_task_triage_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_task_triage_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_task_triage_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_task_triage_preview",
        ),
    ],
)
def test_task_triage_kind_validation_rejects_forged_contracts(
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


def test_task_triage_launch_executes_real_command_translates_and_persists_task_id(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="task-triage-launch"))
    task = SimpleNamespace(task_id="task-bg-123")
    primary = Path("/canonical/sase")

    with (
        patch(
            "sase.bead.task_gate._resolve_task_triage_project_cwd",
            return_value=primary,
        ) as resolve_project,
        patch(
            "sase.bead.task_launch.submit_task_launch_task",
            return_value=task,
        ) as submit,
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["launch"],
            {},
            feedback="Keep the compatibility shim.",
            source="tui",
        )

    assert execution.response["option_results"] == [
        {"id": "launch", "result": {"action": "launch"}}
    ]
    assert execution.response["task_launch_task_id"] == "task-bg-123"
    persisted = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert persisted["task_launch_task_id"] == "task-bg-123"
    translated = translate_task_triage_response(gate.bundle_path, persisted)
    assert translated.bead_id == "sase-task.1"
    assert translated.project == "sase"
    assert translated.title == "Follow up on the cache"
    assert translated.action == "launch"
    assert translated.feedback == "Keep the compatibility shim."
    assert translated.source == "tui"
    resolve_project.assert_called_once_with("sase")
    submit.assert_called_once_with(
        "sase-task.1",
        cwd=primary,
        feedback="Keep the compatibility shim.",
        origin="ace",
    )


def test_task_triage_close_uses_canceled_resolution_reason_and_canonical_commit(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="task-triage-close"))
    primary = Path("/canonical/sase")
    project = MagicMock()
    project.last_mutation_outcome = {
        "closed_ids": ["sase-task.1"],
        "already_closed_ids": [],
        "noted_ids": [],
        "cascade_closed_ids": [],
    }
    mutation = SimpleNamespace(project=project, commit=MagicMock())
    observed: dict[str, Any] = {}

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        observed["auto_commit"] = auto_commit
        observed["cwd"] = cwd
        observed["response_exists_before_mutation"] = gate.response_path.is_file()
        yield mutation

    start_cwd = Path.cwd()
    with (
        patch(
            "sase.bead.task_gate._resolve_task_triage_project_cwd",
            return_value=primary,
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=mutation_scope,
        ),
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["close"],
            {},
            feedback="No longer worth pursuing.",
            source="mobile",
        )

    assert Path.cwd() == start_cwd
    assert execution.response["option_results"] == [
        {"id": "close", "result": {"action": "close"}}
    ]
    assert observed["cwd"] == primary
    assert observed["response_exists_before_mutation"] is True
    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason="No longer worth pursuing.",
        resolution="canceled",
    )
    mutation.commit.assert_called_once_with("chore(beads): close sase-task.1")


def test_task_triage_project_resolution_requires_explicit_project_spec(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    project_dir = projects / "sase"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "sase.sase"
    project_file.write_text("PROJECT_NAME: sase\n", encoding="utf-8")
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch("sase.core.paths.sase_projects_dir", return_value=projects),
        patch(
            "sase.bead.task_launch._resolve_task_launch_cwd",
            return_value=primary,
        ) as resolve,
    ):
        result = _resolve_task_triage_project_cwd("sase")

    assert result == primary
    resolve.assert_called_once_with(None, agent_project_file=project_file)
    with (
        patch("sase.core.paths.sase_projects_dir", return_value=projects),
        pytest.raises(GateError) as exc_info,
    ):
        _resolve_task_triage_project_cwd("missing")
    assert exc_info.value.code == "invalid_task_project"


def test_task_triage_commands_reject_nonempty_input(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(_spec(request_id="task-triage-command-input"))
    command_path = gate.bundle_path / TASK_TRIAGE_COMMAND_PATHS["launch"]

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
