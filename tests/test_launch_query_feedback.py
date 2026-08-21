"""Durable-path MRU and unresolved-reference feedback for ``sase run``.

ACE's in-process launch body used to record ``<ctrl+p>`` VCS-xprompt MRU
entries and surface unknown ``#refs`` as a warning toast. Production now
runs ``launch_query()`` in the child ``sase run`` process, so both pieces
of feedback have to travel that path: record after a successful spawn, and
put the toast text on the ``RUN_LAUNCH`` result payload.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.workspace_provider import reset_workflow_metadata_caches
from sase.workspace_provider._hookspec import WorkflowMetadata
from sase.xprompt.unresolved import format_unresolved_references_toast
from tests._workspace_provider_helpers import (
    _restore_xprompt_vcs_caches_on_teardown,
    git_metadata,
)


def _launch_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _git_and_gh_metadata() -> tuple[WorkflowMetadata, ...]:
    return git_metadata() + (
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern=r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="GitHub",
            pre_allocated_env_prefix="SASE_GH",
        ),
    )


def _patch_git_and_gh_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _git_and_gh_metadata)
    monkeypatch.setattr(
        workspace_provider, "get_all_workflow_metadata", _git_and_gh_metadata
    )
    reset_workflow_metadata_caches()
    _restore_xprompt_vcs_caches_on_teardown(monkeypatch)


def _run_successful_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    *,
    scan_unresolved: tuple[str, ...] = (),
    record_mru: MagicMock | None = None,
) -> dict[str, Any]:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    captured: dict[str, Any] = {}

    def _capture_emit(**kwargs: Any) -> None:
        captured.update(kwargs)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.agent.prompt_inputs.missing_required_input_names",
                return_value=[],
            )
        )
        stack.enter_context(
            patch(
                "sase.xprompt.unresolved.scan_query_for_unresolved_references",
                return_value=scan_unresolved,
            )
        )
        stack.enter_context(
            patch(
                "sase.main.query_handler._launch.launch_agents_from_cwd",
                return_value=[_launch_result()],
            )
        )
        stack.enter_context(
            patch(
                "sase.ops.commands.run.emit_run_launch_result",
                side_effect=_capture_emit,
            )
        )
        if record_mru is not None:
            stack.enter_context(
                patch(
                    "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage",
                    record_mru,
                )
            )
        with pytest.raises(SystemExit) as exc_info:
            launch_query(query)

    assert exc_info.value.code == 0
    return captured


def test_launch_query_plain_prompt_records_no_vcs_mru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = MagicMock()

    _run_successful_launch_query(monkeypatch, "do work", record_mru=record)

    record.assert_not_called()


def test_launch_query_does_not_record_default_git_home_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.history.vcs_xprompt_mru import _load_vcs_xprompt_mru

    fake_mru = tmp_path / "vcs_xprompt_mru.json"
    monkeypatch.setattr("sase.history.vcs_xprompt_mru._MRU_FILE", fake_mru)

    _run_successful_launch_query(monkeypatch, "#git:home do work")

    assert _load_vcs_xprompt_mru() == []
    assert not fake_mru.exists()


def test_launch_query_records_explicit_vcs_ref_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = MagicMock()

    _run_successful_launch_query(monkeypatch, "#gh:sase do the work", record_mru=record)

    record.assert_called_once_with("#gh:sase")


def test_launch_query_does_not_record_mru_when_launch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    record = MagicMock()

    with (
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=(),
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage",
            record,
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query("#gh:sase do work")

    assert exc_info.value.code == 1
    record.assert_not_called()


def test_launch_query_runtime_error_emits_failed_typed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    captured: dict[str, Any] = {}

    with (
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=(),
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=RuntimeError("workspace claim failed"),
        ),
        patch(
            "sase.ops.commands.run.emit_run_launch_result",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query("do work")

    assert exc_info.value.code == 1
    assert captured == {"success": False, "message": "workspace claim failed"}


def test_launch_query_partial_multi_prompt_failure_emits_rollback_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.multi_prompt_launcher import MultiPromptPartialLaunchError
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    captured: dict[str, Any] = {}
    error = MultiPromptPartialLaunchError(
        [_launch_result()], RuntimeError("segment exploded")
    )

    with (
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=(),
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=error,
        ),
        patch(
            "sase.agent.partial_launch.rollback_partial_launch_results",
            return_value=SimpleNamespace(
                terminated_pids=(1234,),
                released_workspaces=(("/tmp/projects/proj/proj.sase", 7),),
            ),
        ),
        patch(
            "sase.ops.commands.run.emit_run_launch_result",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query("one\n---\ntwo")

    assert exc_info.value.code == 1
    assert captured["success"] is False
    assert captured["message"] == (
        "partial multi-prompt launch failed after spawning 1 child agent(s); "
        "terminated 1 and released 1 workspace claim(s). Cause: segment exploded"
    )


def test_launch_query_unexpected_exception_emits_typed_result_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import launch_query

    class XPromptArgumentError(ValueError):
        pass

    monkeypatch.delenv("SASE_AGENT", raising=False)
    _patch_git_and_gh_metadata(monkeypatch)
    captured: dict[str, Any] = {}

    with (
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=(),
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=XPromptArgumentError("invalid priority: urgent"),
        ),
        patch(
            "sase.ops.commands.run.emit_run_launch_result",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ),
        pytest.raises(XPromptArgumentError),
    ):
        launch_query("do work")

    assert captured == {
        "success": False,
        "message": "XPromptArgumentError: invalid priority: urgent",
    }


def test_launch_query_puts_unresolved_toast_on_result_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _run_successful_launch_query(
        monkeypatch,
        "do work #reviewww",
        scan_unresolved=("reviewww",),
    )

    assert captured["success"] is True
    assert captured["payload"]["warning_messages"] == [
        format_unresolved_references_toast(("reviewww",))
    ]


def test_launch_query_omits_warning_messages_when_all_refs_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _run_successful_launch_query(monkeypatch, "do work")

    assert captured["success"] is True
    assert "warning_messages" not in captured["payload"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param("do work", None, id="no_tag_no_mention"),
        pytest.param(
            "do a thing and compare with #gh:actstat",
            None,
            id="mention_only_no_leading_tag",
        ),
        pytest.param("#gh:sase do the work", "#gh:sase", id="leading_tag"),
        pytest.param("#git(sase) do work", "#git:sase", id="parenthesized_leading_tag"),
        pytest.param(
            "#gh:sase do work and see #git:other",
            "#gh:sase",
            id="leading_tag_wins_over_later_mention",
        ),
        pytest.param(
            "%id(foo) #gh:sase do work",
            "#gh:sase",
            id="directive_prefixed_leading_tag",
        ),
    ],
)
def test_launched_vcs_xprompt_prefix_uses_leading_tag_semantics(
    monkeypatch: pytest.MonkeyPatch, query: str, expected: str | None
) -> None:
    """The recorded prefix always matches what the launcher itself resolves.

    Regression coverage for Defect 3: this must find the prompt's *leading*
    launch tag, not the first registry-ordered match anywhere in the text.
    """
    _patch_git_and_gh_metadata(monkeypatch)
    from sase.main.query_handler._launch import _launched_vcs_xprompt_prefix

    assert _launched_vcs_xprompt_prefix(query) == expected


def test_launch_query_records_last_segment_of_multi_prompt_at_mru_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every launched segment records one entry, in launch order.

    The last-launched segment ends up at the MRU head because
    ``record_vcs_xprompt_usage`` moves each recorded prefix to the front.
    """
    record = MagicMock()

    _run_successful_launch_query(
        monkeypatch,
        "#gh:sase seg one\n---\n#gh:actstat seg two",
        record_mru=record,
    )

    assert record.call_args_list == [call("#gh:sase"), call("#gh:actstat")]
