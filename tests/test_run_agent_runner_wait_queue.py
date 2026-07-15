"""Integration tests for queued wait handling in ``run_agent_runner``."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import run_agent_runner


def _runner_args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        cl_name="child-cl",
        project_file="/tmp/sase.sase",
        workspace_dir=str(tmp_path / "workspace"),
        output_path=str(tmp_path / "output.log"),
        workspace_num=7,
        workflow_name="ace(run)-20260701010202",
        prompt_file=str(tmp_path / "prompt.md"),
        timestamp="20260701010202",
        update_target="",
        project_name="sase",
        is_home_mode=False,
    )


def _agent_info() -> SimpleNamespace:
    return SimpleNamespace(
        name="foo--reviewer",
        wait_names=["foo"],
        wait_identity_deps=[
            {
                "project_name": "sase",
                "timestamp": "20260701010101",
                "artifact_dir": "/tmp/foo-parent",
                "name": "foo",
            }
        ],
        wait_duration=None,
        wait_until=None,
        wait_runners=None,
        model="gpt-5",
        llm_provider="codex",
        vcs_provider=None,
        hidden=False,
        approve=False,
        meta={"name": "foo--reviewer"},
        local_xprompts={},
    )


def _run_runner_with_wait_result(
    tmp_path: Path,
    wait_result: object,
) -> dict[str, object]:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    done_markers: list[tuple[str, dict[str, object]]] = []
    shutdown_states: list[object] = []
    exec_result = SimpleNamespace(
        outcome="completed",
        success=True,
        saved_path=None,
        diff_path=None,
        markdown_pdf_paths=[],
        markdown_source_count=0,
        image_paths=[],
        video_paths=[],
        current_artifacts_dir=str(artifacts_dir),
        step_output=None,
    )

    def apply_retry_chain_to_meta(**kwargs: object) -> dict[str, object]:
        return dict(kwargs["agent_meta"])  # type: ignore[arg-type]

    def finalize_runner_shutdown(**kwargs: object) -> None:
        shutdown_states.append(kwargs["state"])

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "parse_runner_args",
                return_value=_runner_args(tmp_path),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "read_prompt_file",
                return_value="%n(foo, reviewer)\nDo work",
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner, "install_workspace_release_sigterm_handler")
        )
        stack.enter_context(patch.object(run_agent_runner, "init_telemetry"))
        stack.enter_context(patch.object(run_agent_runner, "register_push_on_exit"))
        stack.enter_context(patch.object(run_agent_runner, "print_agent_start_banner"))
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "setup_artifacts_directory",
                return_value=("sase", "20260701010202", str(artifacts_dir)),
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner, "write_submitted_xprompt_artifact")
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "preprocess_prompt_xprompts",
                return_value=(
                    "%n(foo, reviewer)\nDo work",
                    None,
                    "%n(foo, reviewer)\nDo work",
                ),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner, "load_retry_handoff_from_env", return_value=None
            )
        )
        stack.enter_context(patch.object(run_agent_runner, "enter_agent_workspace"))
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "extract_directives_and_write_meta",
                return_value=_agent_info(),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "apply_retry_chain_to_meta",
                side_effect=apply_retry_chain_to_meta,
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner, "prepare_workspace_if_needed")
        )
        stack.enter_context(patch.object(run_agent_runner, "bump_spawn_telemetry"))
        wait_for_dependencies = stack.enter_context(
            patch.object(
                run_agent_runner,
                "wait_for_dependencies",
                return_value=wait_result,
            )
        )
        refresh_runner_code_after_wait = stack.enter_context(
            patch.object(run_agent_runner, "refresh_runner_code_after_wait")
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "wait_for_runner_slot",
                side_effect=lambda *_args, claim, **_kwargs: claim(),
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner, "detect_repeat_stop", return_value=None)
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "resolve_agent_refs_in_prompt",
                return_value=("%n(foo, reviewer)\nDo work", None),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "build_output_variable_namespaces",
                return_value=[],
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "record_run_started_at",
                return_value="2026-07-01T01:02:03+00:00",
            )
        )
        run_execution_loop = stack.enter_context(
            patch.object(
                run_agent_runner,
                "run_execution_loop",
                return_value=exec_result,
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "write_done_marker_and_update_index",
                side_effect=lambda artifact_dir, marker: done_markers.append(
                    (artifact_dir, marker)
                ),
            )
        )
        notify = stack.enter_context(
            patch("sase.notifications.senders.notify_workflow_complete")
        )
        stack.enter_context(patch.object(run_agent_runner, "record_completion_metrics"))
        stack.enter_context(
            patch.object(
                run_agent_runner, "format_agent_run_runtime", return_value="0s"
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "finalize_runner_shutdown",
                side_effect=finalize_runner_shutdown,
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner, "was_killed", return_value=False)
        )
        with pytest.raises(SystemExit) as exc_info:
            run_agent_runner.main()

    assert exc_info.value.code == 0
    return {
        "done_markers": done_markers,
        "notify": notify,
        "run_execution_loop": run_execution_loop,
        "shutdown_states": shutdown_states,
        "wait_for_dependencies": wait_for_dependencies,
        "refresh_runner_code_after_wait": refresh_runner_code_after_wait,
    }


def test_queued_child_proceeds_after_identity_wait_barrier(tmp_path: Path) -> None:
    result = _run_runner_with_wait_result(tmp_path, None)

    wait_for_dependencies = result["wait_for_dependencies"]
    assert isinstance(wait_for_dependencies, MagicMock)
    assert wait_for_dependencies.call_args.kwargs["wait_identity_deps"] == [
        {
            "project_name": "sase",
            "timestamp": "20260701010101",
            "artifact_dir": "/tmp/foo-parent",
            "name": "foo",
        }
    ]

    run_execution_loop = result["run_execution_loop"]
    assert isinstance(run_execution_loop, MagicMock)
    run_execution_loop.assert_called_once()
    assert result["done_markers"] == []


def test_runner_forwards_blocking_wait_result_to_code_refresh(tmp_path: Path) -> None:
    result = _run_runner_with_wait_result(tmp_path, True)

    refresh = result["refresh_runner_code_after_wait"]
    assert isinstance(refresh, MagicMock)
    refresh.assert_called_once_with(
        run_agent_runner._STARTUP_CODE_IDENTITY,
        blocking_wait_occurred=True,
        killed=False,
        prompt_file=str(tmp_path / "prompt.md"),
        submitted_xprompt="%n(foo, reviewer)\nDo work",
    )
