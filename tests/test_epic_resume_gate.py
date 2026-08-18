"""Trusted EpicResume gate construction, validation, and side-effect coverage."""

from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.bead.epic_resume_gate import (
    EPIC_RESUME_PREVIEW_PATH,
    EpicResumeResponse,
    cancel_epic_resume,
    create_epic_resume_gate,
    execute_epic_resume_gate_command,
    resume_stalled_epic,
    translate_epic_resume_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.registry import adapter_for_kind
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.priority import is_priority
from sase.notifications.store import load_notifications
from tests._epic_resume_gate_helpers import (
    DEFAULT_STALLED_SINCE,
    epic_resume_member,
    epic_resume_spec,
    expected_resume_argv,
)


def test_epic_resume_gate_builds_canonical_spec_preview_and_pending_action(
    gate_home: Path,
) -> None:
    del gate_home
    failed = [epic_resume_member()]
    waiting = [
        epic_resume_member(
            agent_name="sase-p4.3",
            bead_id="sase-p4.3",
            finished_at=None,
        ),
        epic_resume_member(
            agent_name="sase-p4.land",
            bead_id="sase-p4.land",
            finished_at=None,
        ),
    ]
    gate = create_epic_resume_gate(
        request_id="epic-resume-canonical",
        project="sase",
        epic_id="sase-p4",
        epic_title="Raise an EpicResume gate when a failed phase agent stalls an epic",
        clan_generation=1,
        failed_members=failed,
        waiting_members=waiting,
        remaining_phase_count=2,
        stalled_since=DEFAULT_STALLED_SINCE,
        producer={"chop": "epic_resume"},
    )

    request = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request["kind"] == "epic_resume"
    assert request["query"] == "resume"
    assert request["branches"] == [["resume"]]
    assert request["primary_branch"] == ["resume"]
    assert request["auto"] == {"enabled": False, "argument": None}
    assert request["gate_timeout_seconds"] is None
    assert request["payload"] == {
        "project": "sase",
        "epic_id": "sase-p4",
        "epic_title": "Raise an EpicResume gate when a failed phase agent stalls an epic",
        "clan_generation": "1",
        "failed_members": failed,
        "waiting_members": waiting,
        "remaining_phase_count": 2,
        "resume_argv": expected_resume_argv(),
        "stalled_since": DEFAULT_STALLED_SINCE,
    }
    [resume_option] = request["options"]
    assert resume_option["id"] == "resume"
    assert resume_option["label"] == "Resume epic"
    assert resume_option["icon"] == "▶️"
    assert resume_option["feedback"] == "optional"
    assert resume_option["result_schema"]["properties"]["action"]["const"] == "resume"
    assert request["presentation"]["sender"] == "bead"
    assert request["presentation"]["icon"] == "🔁"
    assert request["presentation"]["title"] == "sase-p4 — Resume stalled epic"
    assert request["presentation"]["notes"] == [
        "sase-p4 — Raise an EpicResume gate when a failed phase agent stalls "
        "an epic · 1 failed agent: sase-p4.1"
    ]
    assert request["presentation"]["tags"] == ["bead", "epic", "resume"]
    assert request["presentation"]["panel"] == "beads"
    assert request["presentation"]["panel_icon"] == "◈"
    assert "origin_agent" not in request["presentation"]
    preview = (gate.bundle_path / EPIC_RESUME_PREVIEW_PATH).read_text(encoding="utf-8")
    assert "# Resume stalled epic sase-p4" in preview
    assert "sase-p4.1" in preview
    assert "sase-p4.3" in preview
    assert "2 phases" in preview
    assert "sase bead work sase-p4 --yes-to-all" in preview
    assert DEFAULT_STALLED_SINCE in preview

    [notification] = load_notifications()
    assert notification.action == "EpicResume"
    assert notification.sender == "bead"
    assert notification.icon == "🔁"
    assert notification.tags == ["bead", "epic", "resume"]
    assert notification.action_data["panel"] == "beads"
    assert notification.action_data["panel_icon"] == "◈"
    assert is_priority(notification)
    [entry] = pending_actions.read_pending_action_store()["actions"].values()
    assert entry["action_kind"] == "epic_resume"
    adapter = adapter_for_kind("epic_resume")
    assert adapter.auto_policy == "forbidden"
    assert adapter.generic_form is True
    assert adapter.neutral_only is True
    assert adapter.default_feedback == "optional"
    assert adapter.display_title == "Epic Resume"
    assert adapter.action == "EpicResume"


def test_epic_resume_round_trip_validates_byte_for_byte(gate_home: Path) -> None:
    del gate_home
    spec = epic_resume_spec(request_id="epic-resume-round-trip")
    gate = create_gate(spec)
    persisted = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert persisted["payload"]["resume_argv"] == expected_resume_argv()
    assert persisted["resources"]


def test_epic_resume_rejects_automatic_resolution(gate_home: Path) -> None:
    del gate_home
    spec = epic_resume_spec(request_id="epic-resume-auto")
    spec["auto"] = True

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "auto_not_supported"


def _preview_resource(spec: dict[str, Any]) -> dict[str, Any]:
    return next(
        resource
        for resource in spec["resources"]
        if resource["path"] == EPIC_RESUME_PREVIEW_PATH
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda spec: spec.update(continuation_mode="task_triage"),
            "invalid_epic_resume_continuation",
        ),
        (
            lambda spec: spec["options"][0].update(label="Relaunch"),
            "invalid_epic_resume_options",
        ),
        (
            lambda spec: spec["payload"].update(extra="forged"),
            "invalid_epic_resume_payload",
        ),
        (
            lambda spec: spec["payload"].update(failed_members=[]),
            "invalid_epic_resume_payload",
        ),
        (
            lambda spec: spec["payload"].update(
                resume_argv=["sase", "bead", "work", "sase-p4"]
            ),
            "invalid_epic_resume_payload",
        ),
        (
            lambda spec: spec["resources"][0].update(content="#!/bin/sh\nexit 0\n"),
            "invalid_epic_resume_command",
        ),
        (
            lambda spec: spec["resources"].append(
                {
                    "path": "forged.txt",
                    "role": "attachment",
                    "content": "unexpected",
                }
            ),
            "invalid_epic_resume_resources",
        ),
        (
            lambda spec: spec["presentation"].update(panel="reviews"),
            "invalid_epic_resume_presentation",
        ),
        (
            lambda spec: spec["presentation"].update(origin_agent="forged-agent"),
            "invalid_epic_resume_presentation",
        ),
        (
            lambda spec: _preview_resource(spec).update(
                content=_preview_resource(spec)["content"].replace(
                    "sase-p4.1", "forged-agent"
                )
            ),
            "invalid_epic_resume_preview",
        ),
    ],
)
def test_epic_resume_kind_validation_rejects_forged_contracts(
    gate_home: Path,
    mutation: Any,
    code: str,
) -> None:
    del gate_home
    spec = deepcopy(epic_resume_spec(request_id=f"forged-{code}"))
    mutation(spec)

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == code


def test_epic_resume_command_rejects_nonempty_input(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(epic_resume_spec(request_id="epic-resume-command-input"))
    command_path = gate.bundle_path / "commands" / "resume"

    completed = subprocess.run(
        [str(command_path)],
        cwd=gate.bundle_path,
        input=b'{"unexpected": true}\n',
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert b"must be empty" in completed.stderr


def _run_execute(raw: object) -> tuple[int, str, str]:
    stdin = io.StringIO(raw if isinstance(raw, str) else json.dumps(raw) + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
    try:
        code = execute_epic_resume_gate_command()
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
    return code, stdout.getvalue(), stderr.getvalue()


def test_epic_resume_command_emits_resume_action_for_empty_object() -> None:
    code, stdout, stderr = _run_execute({})
    assert code == 0
    assert stderr == ""
    assert json.loads(stdout) == {"action": "resume"}


def test_epic_resume_command_rejects_non_object_stdin() -> None:
    code, _stdout, stderr = _run_execute([1, 2])
    assert code == 2
    assert "must be an object" in stderr


def test_epic_resume_translation_reads_identity_from_the_request(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(epic_resume_spec(request_id="epic-resume-translate"))

    translated = translate_epic_resume_response(
        gate.bundle_path,
        {
            "selected_option_ids": ["resume"],
            "option_results": [{"id": "resume", "result": {"action": "resume"}}],
            "feedback": "try again",
            "source": "mobile",
        },
    )

    assert translated == EpicResumeResponse(
        project="sase",
        epic_id="sase-p4",
        action="resume",
        feedback="try again",
        source="mobile",
    )


def test_epic_resume_translation_rejects_a_forged_epic_id_in_the_result(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(epic_resume_spec(request_id="epic-resume-forged-id"))

    translated = translate_epic_resume_response(
        gate.bundle_path,
        {
            "selected_option_ids": ["resume"],
            "option_results": [
                {
                    "id": "resume",
                    "result": {"action": "resume", "epic_id": "sase-other"},
                }
            ],
            "source": "tui",
        },
    )

    assert translated.epic_id == "sase-p4"


def test_epic_resume_apply_side_effects_submits_exactly_one_resume_proc(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(epic_resume_spec(request_id="epic-resume-launch"))
    task = SimpleNamespace(proc_id="epic-resume-bg-123")

    with patch(
        "sase.bead.epic_resume_launch.submit_epic_resume_task",
        return_value=task,
    ) as submit:
        execution = execute_gate_selection(
            gate.bundle_path,
            ["resume"],
            {},
            feedback="Retry the stalled clan.",
            source="tui",
        )

    assert execution.response["option_results"] == [
        {"id": "resume", "result": {"action": "resume"}}
    ]
    assert execution.response["epic_resume_task_id"] == "epic-resume-bg-123"
    persisted = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert persisted["epic_resume_task_id"] == "epic-resume-bg-123"
    translated = translate_epic_resume_response(gate.bundle_path, persisted)
    assert translated.epic_id == "sase-p4"
    assert translated.project == "sase"
    assert translated.action == "resume"
    assert translated.feedback == "Retry the stalled clan."
    assert translated.source == "tui"
    submit.assert_called_once_with(
        "sase-p4",
        project="sase",
        origin="ace",
    )


def test_resume_stalled_epic_rejects_a_mismatched_action() -> None:
    decision = EpicResumeResponse(
        project="sase",
        epic_id="sase-p4",
        action="close",  # type: ignore[arg-type]
        feedback=None,
        source="tui",
    )
    with pytest.raises(GateError) as exc_info:
        resume_stalled_epic(decision)
    assert exc_info.value.code == "invalid_epic_resume_action"


def test_cancel_epic_resume_settles_gate_and_is_idempotent(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(epic_resume_spec(request_id="epic-resume-cancel"))

    assert cancel_epic_resume("sase", "sase-p4", reason="epic_resumed", source="axe")
    assert (gate.bundle_path / "cancellation.json").is_file()
    assert not cancel_epic_resume("sase", "sase-p4", reason="epic_resumed")


def test_cancel_epic_resume_treats_already_answered_as_benign(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(epic_resume_spec(request_id="epic-resume-answered-race"))
    error = GateError("already_answered", "response.json", "already answered")
    with patch("sase.notification_gates.executor.cancel_gate", side_effect=error):
        assert not cancel_epic_resume("sase", "sase-p4", reason="race")
