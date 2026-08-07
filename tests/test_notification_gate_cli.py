"""CLI and path-compatibility coverage for notification gates."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pytest

from sase.main.gate_handler import handle_gate_command
from sase.main.notify_handler import handle_notify_command
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.paths import resolve_action_bundle
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from tests._notification_gates_fixtures import custom_gate_spec, gate_spec


def test_gate_wait_prints_stable_answered_json_and_human_summary(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    result = create_gate(custom_gate_spec(request_id="wait-answered"))
    execute_gate_selection(
        result.bundle_path,
        ["proceed", "audit"],
        feedback="Looks good",
    )
    args = argparse.Namespace(
        gate_subcommand="wait",
        id="wait-answered",
        kind="custom",
        json=True,
        timeout=None,
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "answered",
        "selected_option_ids": ["proceed", "audit"],
        "feedback": "Looks good",
        "response_path": str(result.response_path),
    }

    args.json = False
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(args)

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "Gate custom/wait-answered answered" in out
    assert "options proceed, audit" in out
    assert f"Response path: {result.response_path}" in out


def test_gate_wait_reports_cancelled_gate_with_distinct_exit_code(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    result = create_gate(gate_spec(request_id="wait-cancelled"))
    cancel_gate(result.bundle_path, source="test")

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(
            argparse.Namespace(
                gate_subcommand="wait",
                id="wait-cancelled",
                kind="hitl",
                json=True,
                timeout=None,
            )
        )

    assert excinfo.value.code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "cancelled"
    assert payload["selected_option_ids"] == []
    assert payload["feedback"] is None
    assert payload["response_path"] == str(result.response_path)


def test_gate_wait_reports_cli_timeout_with_distinct_exit_code(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    result = create_gate(gate_spec(request_id="wait-timeout"))

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(
            argparse.Namespace(
                gate_subcommand="wait",
                id="wait-timeout",
                kind="hitl",
                json=True,
                timeout=0.0,
            )
        )

    assert excinfo.value.code == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "timeout"
    assert payload["response_path"] == str(result.response_path)
    cancellation = json.loads(
        (result.bundle_path / "cancellation.json").read_text(encoding="utf-8")
    )
    assert cancellation["reason"] == "timeout"


def test_gate_create_json_and_raw_notify_privileged_rejection(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(gate_spec())))
    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(
            argparse.Namespace(
                gate_subcommand="create",
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["schema_version"] == 2
    assert descriptor["kind"] == "hitl"

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "raw", "action": "PlanApproval"})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 1
    assert "privileged" in capsys.readouterr().err


def test_gate_create_presentation_overrides_reach_notification(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(gate_spec())))

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(
            argparse.Namespace(
                gate_subcommand="create",
                origin_agent="  filer.agent  ",
                panel=" Reviews ",
                sender=None,
                tag=None,
            )
        )

    assert excinfo.value.code == 0
    capsys.readouterr()
    [notification] = load_notifications(include_dismissed=True)
    assert notification.action_data["panel"] == "reviews"
    assert notification.action_data["origin_agent"] == "filer.agent"


def test_raw_notify_creation_preserves_silent(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "raw", "silent": True})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 0
    assert load_notifications(include_dismissed=True)[0].silent is True


def test_raw_notify_cannot_spoof_custom_gate_and_custom_has_no_legacy_fallback(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "raw", "action": "CustomGate"})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 1
    assert "privileged" in capsys.readouterr().err

    legacy = gate_home / "legacy-custom"
    legacy.mkdir()
    (legacy / "request.json").write_text("{}\n", encoding="utf-8")
    assert resolve_action_bundle("CustomGate", {"bundle_path": str(legacy)}) is None


@pytest.mark.parametrize(
    (
        "action",
        "kind",
        "legacy_key",
        "legacy_request",
        "legacy_response",
    ),
    [
        (
            "PlanApproval",
            "plan",
            "response_dir",
            "plan_request.json",
            "plan_response.json",
        ),
        (
            "EpicApproval",
            "epic_plan",
            "response_dir",
            "plan_request.json",
            "plan_response.json",
        ),
        (
            "UserQuestion",
            "question",
            "response_dir",
            "question_request.json",
            "question_response.json",
        ),
        (
            "LaunchApproval",
            "launch",
            "response_dir",
            "launch_request.json",
            "launch_response.json",
        ),
        (
            "HITL",
            "hitl",
            "artifacts_dir",
            "hitl_request.json",
            "hitl_response.json",
        ),
    ],
)
def test_typed_gate_resolver_keeps_neutral_first_legacy_fallback_contract(
    gate_home: Path,
    action: str,
    kind: str,
    legacy_key: str,
    legacy_request: str,
    legacy_response: str,
) -> None:
    """Keep legacy readers until the documented post-release removal window."""
    request_id = f"{kind}-compatibility"
    neutral_root = gate_home / "requests" / kind / request_id
    neutral_root.mkdir(parents=True)
    neutral_request = neutral_root / "request.json"
    neutral_request.write_text("{}\n", encoding="utf-8")

    legacy_root = gate_home / f"legacy-{kind}"
    legacy_root.mkdir()
    (legacy_root / legacy_request).write_text("{}\n", encoding="utf-8")
    action_data = {
        "request_id": request_id,
        "request_kind": kind,
        legacy_key: str(legacy_root),
    }

    neutral = resolve_action_bundle(action, action_data)
    assert neutral is not None
    assert neutral.root == neutral_root
    assert neutral.request == neutral_request
    assert neutral.response == neutral_root / "response.json"
    assert neutral.legacy is False

    neutral_request.unlink()
    legacy = resolve_action_bundle(action, action_data)
    assert legacy is not None
    assert legacy.root == legacy_root
    assert legacy.request == legacy_root / legacy_request
    assert legacy.response == legacy_root / legacy_response
    assert legacy.legacy is True


def test_gate_create_missing_title_prints_error_and_exits_1(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    spec = custom_gate_spec()
    presentation = spec["presentation"]
    assert isinstance(presentation, dict)
    del presentation["title"]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(spec)))

    with pytest.raises(SystemExit) as excinfo:
        handle_gate_command(
            argparse.Namespace(
                gate_subcommand="create",
                sender=None,
                tag=None,
            )
        )

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "Error [missing_presentation] presentation.title:" in err
