"""Stage LaunchApproval requests and agent-origin ``sase run`` entries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.gate_intent import list_gate_intents
from sase.agent.launch_request import (
    LaunchRequestCreationResult,
    LaunchRequestError,
    StagedLaunchRequestCreationResult,
    cancel_launch_approval_request,
    create_launch_approval_request,
    create_launch_approval_request_from_prompt,
    wait_for_launch_approval,
)
from sase.agent.launch_request_followup import launch_next_action
from sase.agent.pending_handoff import PIPE_PENDING_MARKER
from sase.agent.pending_handoff_write import write_pending_handoff_marker
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    STAGING_RESERVATION_FILENAME,
    read_staged_handoff,
)
from sase.feature_flags import override_flags
from sase.gate_turn.publisher import publish_staged_gate
from sase.launch_approval_actions import (
    _LaunchApprovalActionContext,
    execute_launch_approval_response,
)
from sase.main.launch_handler import handle_launch_command
from sase.main.query_handler._launch import launch_query
from sase.notification_gates.paths import bundle_paths
from tests.monitor._fixtures import make_starter_agent, write_project_file


def _prepare_creator(
    monkeypatch: pytest.MonkeyPatch, project: str, name: str = "lane"
) -> str:
    write_project_file(project)
    creator_dir = make_starter_agent(
        project,
        "20261029120000",
        name,
        agent_session=name,
        agent_session_role="root",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", creator_dir)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_BEAD_ID", "sase-demo.1")
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    import sase.gate_turn.agent_handoff as agent_handoff
    import sase.gate_turn as gate_turn_pkg

    monkeypatch.setattr(
        agent_handoff, "will_handoff_gate_to_agent_runner", lambda: False
    )
    monkeypatch.setattr(
        gate_turn_pkg,
        "will_handoff_gate_to_agent_runner",
        lambda: False,
        raising=False,
    )
    return creator_dir


def _stage_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    prompt: str = "Do work",
    max_slots: int = 1,
) -> tuple[StagedLaunchRequestCreationResult, str]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    creator_dir = _prepare_creator(monkeypatch, "launch-staged")
    with override_flags(staged_handoffs=True):
        result = create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": prompt,
                "reason": "Need a helper",
                "max_slots": max_slots,
            }
        )
    assert isinstance(result, StagedLaunchRequestCreationResult)
    return result, creator_dir


def test_agent_launch_request_stages_when_flag_enabled(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    spawned: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda *_a, **_k: spawned.append("spawned"),
    )
    result, creator_dir = _stage_launch(monkeypatch, tmp_path)

    payload = result.to_dict()
    assert payload["status"] == "staged"
    assert payload["kind"] == "launch"
    assert payload["request_id"] == result.request_id
    assert payload["staged_id"]
    assert payload["workspace_mode"] == "inherit"
    assert "notification_id" not in payload
    assert "gate_turn" not in payload
    assert "response_dir" not in payload
    staged = read_staged_handoff(creator_dir)
    assert staged is not None
    assert staged["kind"] == "gate"
    assert staged["payload"]["request_id"] == result.request_id
    assert staged["payload"]["spec"]["payload"]["typed_plan"]["units"]
    assert (Path(creator_dir) / STAGED_HANDOFF_FILENAME).is_file()
    assert not (Path(creator_dir) / STAGING_RESERVATION_FILENAME).exists()
    assert not (Path(creator_dir) / ".sase_gate_pending").exists()
    assert list_gate_intents(creator_dir) == []
    assert not bundle_paths("launch", result.request_id).root.exists()
    assert spawned == []


def test_human_origin_launch_request_still_publishes_with_flag_on(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    with override_flags(staged_handoffs=True):
        result = create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": "Do work",
                "reason": "Human origin",
                "max_slots": 1,
            }
        )
    assert isinstance(result, LaunchRequestCreationResult)
    assert result.notification_id
    assert result.preview_path.is_file()
    assert result.response_dir.exists()


def test_invalid_auto_is_rejected_before_publication(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    creator_dir = _prepare_creator(monkeypatch, "launch-auto")
    original = __import__(
        "sase.agent.launch_request_gate", fromlist=["launch_gate_spec"]
    ).launch_gate_spec

    def auto_spec(*args: Any, **kwargs: Any) -> dict[str, Any]:
        spec = original(*args, **kwargs)
        spec["auto"] = True
        return spec

    monkeypatch.setattr("sase.agent.launch_request_gate.launch_gate_spec", auto_spec)
    monkeypatch.setattr("sase.agent.launch_request._launch_gate_spec", auto_spec)
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(LaunchRequestError, match="cannot auto-execute"),
    ):
        create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": "Do work",
                "reason": "Need a helper",
                "max_slots": 1,
            }
        )
    assert read_staged_handoff(creator_dir) is None
    assert not (Path(creator_dir) / STAGING_RESERVATION_FILENAME).exists()
    from sase.notifications.store import load_notifications

    assert load_notifications(include_dismissed=False) == []


def test_max_slots_and_continuation_conflicts_leave_no_published_gate(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    creator_dir = _prepare_creator(monkeypatch, "launch-invalid")
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(LaunchRequestError, match="max_slots"),
    ):
        create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": "one\n---\ntwo",
                "reason": "too many slots",
                "max_slots": 1,
            }
        )
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(LaunchRequestError, match="requester's agent-session lane"),
    ):
        create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": "%i(reviewer, session=parent)\nReview",
                "reason": "Need reviewer",
                "max_slots": 1,
            }
        )
    assert read_staged_handoff(creator_dir) is None
    assert not (Path(creator_dir) / STAGING_RESERVATION_FILENAME).exists()
    from sase.notifications.store import load_notifications

    assert load_notifications(include_dismissed=False) == []


def test_second_handoff_is_refused_before_publication(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    creator_dir = _prepare_creator(monkeypatch, "launch-second")
    write_pending_handoff_marker(
        PIPE_PENDING_MARKER,
        {"prompt": "already handed off"},
        artifacts_dir=creator_dir,
    )
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(LaunchRequestError, match="already exists"),
    ):
        create_launch_approval_request(
            {
                "schema_version": 1,
                "prompt": "Do work",
                "reason": "Need a helper",
                "max_slots": 1,
            }
        )
    from sase.notifications.store import load_notifications

    assert load_notifications(include_dismissed=False) == []


def test_typed_plan_and_continuation_survive_adoption(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    pytest.importorskip("sase_core_rs")
    result, creator_dir = _stage_launch(monkeypatch, tmp_path, prompt="Do work")
    staged = read_staged_handoff(creator_dir)
    assert staged is not None
    staged_plan = staged["payload"]["spec"]["payload"]["typed_plan"]
    staged_digest = staged_plan["content_digest"]
    continuation = staged["payload"]["spec"]["payload"]["requester_continuation"]
    assert continuation["mode"] == "resume_requester"
    assert continuation["resume_branches"] == [
        "approve",
        "reject",
        "timeout",
        "failed",
    ]
    assert continuation["terminal_branches"] == ["stopped"]

    creation = publish_staged_gate(
        staged["payload"],
        staged_id=str(staged["staged_id"]),
        artifacts_dir=creator_dir,
    )
    envelope = json.loads(creation.gate.request_path.read_text(encoding="utf-8"))
    published_plan = envelope["payload"]["typed_plan"]
    assert published_plan["content_digest"] == staged_digest
    assert published_plan == staged_plan
    published_continuation = envelope["payload"]["requester_continuation"]
    assert published_continuation["mode"] == "resume_requester"
    assert published_continuation["resume_branches"] == continuation["resume_branches"]
    assert published_continuation["terminal_branches"] == ["stopped"]

    context = _LaunchApprovalActionContext(
        id=str(creation.gate.notification_id),
        host_files=(str(creation.gate.preview_path),),
        host_action_data={
            "request_id": creation.gate.request_id,
            "request_kind": "launch",
            "response_dir": str(creation.gate.bundle_path),
        },
    )
    reject = execute_launch_approval_response(
        context, "reject", feedback="Narrow the request"
    )
    assert reject.response_json["selected_option_ids"] == ["reject"]
    assert (
        launch_next_action(
            envelope=envelope,
            response=reject.response_json,
            gate_state="answered",
        )
        is not None
    )
    assert (
        "rejected"
        in (
            launch_next_action(
                envelope=envelope,
                response=reject.response_json,
                gate_state="answered",
            )
            or ""
        ).lower()
    )
    approve_text = launch_next_action(
        envelope=envelope,
        response={
            "selected_option_ids": ["approve"],
            "options": [
                {
                    "id": "approve",
                    "result": {"action": "approve", "dispatch_status": "ok"},
                }
            ],
        },
        gate_state="answered",
    )
    assert approve_text is not None
    assert "approve was selected" in approve_text.lower()
    timeout_text = launch_next_action(
        envelope=envelope, response={}, gate_state="timeout"
    )
    assert timeout_text is not None and "timed out" in timeout_text.lower()
    stopped_text = launch_next_action(
        envelope=envelope, response={}, gate_state="stopped"
    )
    assert stopped_text is None


def test_launch_request_cli_emits_staged_descriptor(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    creator_dir = _prepare_creator(monkeypatch, "launch-cli")
    args = argparse.Namespace(
        launch_subcommand="request",
        output="json",
        prompt="Do work",
        reason="Need a helper",
        max_slots=1,
        payload=None,
        payload_file=None,
        approval="required",
        source=None,
    )
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_launch_command(args)
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    descriptor = json.loads(captured.out)
    assert descriptor["status"] == "staged"
    assert descriptor["kind"] == "launch"
    assert "Staged" in captured.err
    assert "/sase_final" in captured.err
    assert read_staged_handoff(creator_dir) is not None
    assert not bundle_paths("launch", descriptor["request_id"]).root.exists()


def test_agent_origin_run_stages_instead_of_spawning(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    creator_dir = _prepare_creator(monkeypatch, "launch-run")
    spawned: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda *_a, **_k: spawned.append("spawned"),
    )
    monkeypatch.setattr(
        "sase.agent.prompt_inputs.missing_required_input_names",
        lambda _query: [],
    )
    monkeypatch.setattr(
        "sase.macro.unresolved.scan_query_for_unresolved_references",
        lambda _query: [],
    )
    monkeypatch.setattr(
        "sase.ops.cli.load_request",
        lambda *_a, **_k: argparse.Namespace(payload={}),
    )
    with (
        override_flags(staged_handoffs=True),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query("Do work")
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    descriptor = json.loads(captured.out)
    assert descriptor["status"] == "staged"
    assert descriptor["kind"] == "launch"
    assert "Staged" in captured.err
    assert spawned == []
    assert read_staged_handoff(creator_dir) is not None


def test_flag_off_agent_request_still_publishes(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    _prepare_creator(monkeypatch, "launch-flag-off")
    with override_flags(staged_handoffs=False):
        result = create_launch_approval_request_from_prompt(
            "Do work",
            reason="Need a helper",
        )
    assert isinstance(result, LaunchRequestCreationResult)
    assert result.notification_id
    assert result.gate_turn_creation is not None
    assert result.preview_path.is_file()


def test_wait_and_cancel_reject_staged_results() -> None:
    staged = StagedLaunchRequestCreationResult(
        request_id="launch-1",
        staged_id="stage-1",
        workspace_mode="inherit",
        request={},
        instruction="finish",
    )
    with pytest.raises(LaunchRequestError, match="cannot wait"):
        wait_for_launch_approval(staged)
    with pytest.raises(LaunchRequestError, match="cannot cancel"):
        cancel_launch_approval_request(staged)


def test_flag_off_launch_request_cli_emits_published_descriptor(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    _prepare_creator(monkeypatch, "launch-cli-off")
    args = argparse.Namespace(
        launch_subcommand="request",
        output="json",
        prompt="Do work",
        reason="Need a helper",
        max_slots=1,
        payload=None,
        payload_file=None,
        approval="required",
        source=None,
    )
    with (
        override_flags(staged_handoffs=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_launch_command(args)
    assert exc_info.value.code == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert "notification_id" in descriptor
    assert descriptor.get("status") != "staged"
    assert bundle_paths("launch", descriptor["request_id"]).root.exists()


def test_flag_off_agent_origin_run_publishes_instead_of_spawning(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    _prepare_creator(monkeypatch, "launch-run-off")
    spawned: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda *_a, **_k: spawned.append("spawned"),
    )
    monkeypatch.setattr(
        "sase.agent.prompt_inputs.missing_required_input_names",
        lambda _query: [],
    )
    monkeypatch.setattr(
        "sase.macro.unresolved.scan_query_for_unresolved_references",
        lambda _query: [],
    )
    monkeypatch.setattr(
        "sase.ops.cli.load_request",
        lambda *_a, **_k: argparse.Namespace(payload={}),
    )
    with (
        override_flags(staged_handoffs=False),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query("Do work")
    assert exc_info.value.code == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert "notification_id" in descriptor
    assert descriptor.get("status") != "staged"
    assert spawned == []
