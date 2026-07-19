"""Tests for special case handling in sase run command."""

import json
from unittest.mock import MagicMock, patch

import pytest

from sase.main.query_handler.special_cases import handle_run_special_cases
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _mock_workflow_names() -> MagicMock:
    """Return a mock for get_workflow_names returning standard VCS names."""
    return MagicMock(return_value={"gh", "git", "spy"})


def test_vcs_dot_prompt_single_arg_triggers_history_picker() -> None:
    """Test that '#gh:sase .' as a single arg triggers the prompt history picker."""
    mock_picker = MagicMock(return_value="selected prompt")
    mock_names = _mock_workflow_names()
    with (
        patch(
            "sase.main.query_handler.special_cases.show_prompt_history_picker",
            mock_picker,
        ),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        patch("sase.workspace_provider.get_workflow_names", mock_names),
        patch("sase.workspace_provider._registry.get_workflow_names", mock_names),
        patch("sase.xprompt._parsing._VCS_TAG_PATTERN", None),
        pytest.raises(SystemExit),
    ):
        handle_run_special_cases(["#gh:sase ."])

    mock_picker.assert_called_once_with()
    mock_launch.assert_called_once_with("#gh:sase selected prompt")


def test_vcs_dot_prompt_strips_cross_vcs_prefix() -> None:
    """Test that a different VCS tag is stripped when reusing via another VCS.

    E.g., selecting a prompt originally used with #git:repo while now
    using #gh:sase should strip the #git:repo prefix.
    """
    mock_picker = MagicMock(return_value="#git:repo do something cool")
    mock_names = _mock_workflow_names()
    with (
        patch(
            "sase.main.query_handler.special_cases.show_prompt_history_picker",
            mock_picker,
        ),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        patch("sase.workspace_provider.get_workflow_names", mock_names),
        patch("sase.workspace_provider._registry.get_workflow_names", mock_names),
        patch("sase.xprompt._parsing._VCS_TAG_PATTERN", None),
        pytest.raises(SystemExit),
    ):
        handle_run_special_cases(["#gh:sase", "."])

    # Should strip #git:repo and prepend #gh:sase
    mock_launch.assert_called_once_with("#gh:sase do something cool")


def test_run_special_cases_executes_explicit_standalone_workflow() -> None:
    """sase run '#!sync' launches a detached standalone workflow."""
    workflow = Workflow(
        name="sync",
        steps=[WorkflowStep(name="run", bash="echo sync")],
    )
    with (
        patch("sase.xprompt.get_all_prompts", return_value={"sync": workflow}),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit) as exc,
    ):
        handle_run_special_cases(["#!sync!!"])

    assert exc.value.code == 0
    mock_launch.assert_called_once_with("#!sync!!")


def test_run_special_cases_warns_for_legacy_standalone_workflow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bare #standalone stays compatible but tells users to switch to #!."""
    workflow = Workflow(
        name="sync",
        steps=[WorkflowStep(name="run", bash="echo sync")],
    )
    with (
        patch("sase.xprompt.get_all_prompts", return_value={"sync": workflow}),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit),
    ):
        handle_run_special_cases(["#sync"])

    captured = capsys.readouterr()
    assert "use '#!sync'" in captured.err
    mock_launch.assert_called_once_with("#sync")


def test_run_special_cases_rejects_bang_for_embeddable_workflow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#!commit is invalid when commit has a prompt_part."""
    workflow = Workflow(
        name="commit",
        steps=[WorkflowStep(name="main", prompt_part="Commit context")],
    )
    with (
        patch("sase.xprompt.get_all_prompts", return_value={"commit": workflow}),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit) as exc,
    ):
        handle_run_special_cases(["#!commit"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Only standalone workflows use '#!'" in captured.err
    mock_launch.assert_not_called()


def test_run_single_token_prompt_dispatches_directly() -> None:
    """`sase run hello` runs the prompt instead of dead-ending in argparse.

    Regression test: single-token prompts used to fall through to argparse's
    dispatch-less `run` namespace and exit with "Unknown command: run".
    """
    with (
        patch("sase.xprompt.get_all_prompts", MagicMock(return_value={})),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_run_special_cases(["hello-single-token"])

    assert excinfo.value.code == 0
    mock_launch.assert_called_once_with("hello-single-token")


def test_run_single_flag_like_token_falls_through() -> None:
    """Unknown flag-like tokens still fall through to argparse's error."""
    with (
        patch("sase.xprompt.get_all_prompts", MagicMock(return_value={})),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
    ):
        handled = handle_run_special_cases(["--bogus-flag"])

    assert handled is False
    mock_launch.assert_not_called()


def test_run_deprecated_daemon_flag_warns_and_launches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The hidden -d shim keeps old automation working while warning."""
    with (
        patch("sase.xprompt.get_all_prompts", MagicMock(return_value={})),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        handle_run_special_cases(["-d", "hello-single-token"])

    assert excinfo.value.code == 0
    mock_launch.assert_called_once_with("hello-single-token")
    assert "-d/--daemon is deprecated" in capsys.readouterr().err


def test_run_parsed_prompt_dispatches_fallthrough_namespace() -> None:
    """The entry.py `run` branch routes argparse-parsed prompts to the query path."""
    import argparse

    from sase.main.query_handler.special_cases import run_parsed_prompt

    args = argparse.Namespace(command="run", prompt="known_prompt_name")
    with (
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        run_parsed_prompt(args)

    assert excinfo.value.code == 0
    mock_launch.assert_called_once_with("known_prompt_name")


def test_launch_query_from_agent_context_requests_approval(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running agents request approval instead of spawning children directly."""
    from pathlib import Path
    from types import SimpleNamespace

    from sase.main.query_handler._launch import launch_query

    monkeypatch.setenv("SASE_AGENT", "planner")
    request = SimpleNamespace(
        request_id="launch-test",
        response_path=Path("/tmp/launch_response.json"),
    )
    outcome = SimpleNamespace(
        to_dict=lambda: {
            "status": "rejected",
            "request_id": "launch-test",
            "message": "Launch rejected",
        }
    )
    with (
        patch(
            "sase.agent.prompt_inputs.missing_required_input_names",
            return_value=[],
        ),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch(
            "sase.agent.launch_request.create_launch_approval_request_from_prompt",
            return_value=request,
        ) as mock_request,
        patch(
            "sase.agent.launch_request.wait_for_launch_approval",
            return_value=outcome,
        ) as mock_wait,
        patch("sase.main.query_handler._launch.launch_agents_from_cwd") as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        launch_query("%i(foo, reviewer)\nDo work")

    assert excinfo.value.code == 0
    mock_request.assert_called_once_with(
        "%i(foo, reviewer)\nDo work",
        reason="Running agent requested a detached launch.",
        source_surface="agent_skill",
    )
    mock_wait.assert_called_once_with(request)
    mock_launch.assert_not_called()
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


def test_entry_run_known_prompt_falls_through_to_run_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known prompt names declined by special cases still dispatch via entry.py."""
    import sys

    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "run", "known_prompt_name"])
    with (
        patch(
            "sase.xprompt.get_all_prompts",
            MagicMock(return_value={"known_prompt_name": object()}),
        ),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        entry.main()

    assert excinfo.value.code == 0
    mock_launch.assert_called_once_with("known_prompt_name")
