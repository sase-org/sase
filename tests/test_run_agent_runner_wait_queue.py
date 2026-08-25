"""Integration tests for queued wait handling in ``run_agent_runner``."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import (
    run_agent_runner,
    run_agent_runner_bootstrap,
    run_agent_runner_launch,
)
from sase.agent.force_reuse_bead import SASE_AGENT_FORCE_REUSE_BEAD_ENV
from sase.bead.claims import BEAD_CLAIM_MARKER


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


def _agent_info(*, bead_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        name="foo--reviewer",
        bead_id=bead_id,
        wait_names=["foo"],
        wait_identity_deps=[
            {
                "project_name": "sase",
                "timestamp": "20260701010101",
                "artifact_dir": "/tmp/foo-parent",
                "name": "foo",
            }
        ],
        wait_fork_sources=[],
        wait_beads=["sase-87.2"],
        wait_duration=None,
        wait_until=None,
        wait_runners=None,
        wait_priority=None,
        model="gpt-5",
        llm_provider="codex",
        vcs_provider=None,
        hidden=False,
        approve=False,
        clan_summary_resolution=None,
        meta={"name": "foo--reviewer"},
        local_xprompts={},
    )


def _run_runner_with_wait_result(
    tmp_path: Path,
    wait_result: object,
    *,
    bead_id: str | None = None,
    force_reuse_marker: dict[str, str] | None = None,
) -> dict[str, object]:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    done_markers: list[tuple[str, dict[str, object]]] = []
    shutdown_states: list[object] = []
    lifecycle_events: list[str] = []
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

    def wait_for_dependencies_side_effect(
        _wait_names: object,
        wait_artifacts_dir: str,
        _cl_name: object,
        _timestamp: object,
        agent_meta: dict[str, object],
        **_kwargs: object,
    ) -> object:
        lifecycle_events.append("wait")
        persisted_meta = json.loads(
            (Path(wait_artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert persisted_meta["output_path"] == str(tmp_path / "output.log")
        assert agent_meta["output_path"] == str(tmp_path / "output.log")
        if bead_id is not None:
            claim_marker_path = Path(wait_artifacts_dir) / BEAD_CLAIM_MARKER
            if force_reuse_marker is not None:
                assert not claim_marker_path.exists()
            else:
                claim_marker = json.loads(claim_marker_path.read_text(encoding="utf-8"))
                assert claim_marker == {
                    "agent_name": "foo--reviewer",
                    "bead_id": bead_id,
                    "project_name": "sase",
                }
        return wait_result

    with ExitStack() as stack:
        if force_reuse_marker is not None:
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {SASE_AGENT_FORCE_REUSE_BEAD_ENV: json.dumps(force_reuse_marker)},
                )
            )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "parse_runner_args",
                return_value=_runner_args(tmp_path),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "read_prompt_file",
                return_value="%i(reviewer, family=foo)\nDo work",
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap, "install_workspace_release_sigterm_handler"
            )
        )
        stack.enter_context(patch.object(run_agent_runner_bootstrap, "init_telemetry"))
        stack.enter_context(
            patch.object(run_agent_runner_bootstrap, "register_flush_on_exit")
        )
        stack.enter_context(
            patch.object(run_agent_runner_bootstrap, "print_agent_start_banner")
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "setup_artifacts_directory",
                return_value=("sase", "20260701010202", str(artifacts_dir)),
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner_bootstrap, "write_submitted_xprompt_artifact")
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "preprocess_prompt_xprompts",
                return_value=(
                    "%i(reviewer, family=foo)\nDo work",
                    None,
                    "%i(reviewer, family=foo)\nDo work",
                ),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "load_retry_handoff_from_env",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner_bootstrap, "enter_agent_workspace")
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "extract_directives_and_write_meta",
                return_value=_agent_info(bead_id=bead_id),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "apply_retry_chain_to_meta",
                side_effect=apply_retry_chain_to_meta,
            )
        )
        stack.enter_context(
            patch.object(run_agent_runner_launch, "prepare_workspace_if_needed")
        )
        stack.enter_context(patch.object(run_agent_runner, "bump_spawn_telemetry"))
        wait_for_dependencies = stack.enter_context(
            patch.object(
                run_agent_runner,
                "wait_for_dependencies",
                side_effect=wait_for_dependencies_side_effect,
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
                run_agent_runner_launch,
                "resolve_agent_refs_in_prompt",
                return_value=("%i(reviewer, family=foo)\nDo work", None),
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_launch,
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
        claim_for_wait = stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "claim_bead_for_waiting_agent",
                side_effect=lambda **_kwargs: lifecycle_events.append("claim") or True,
            )
        )
        retain_for_replacement = stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "retain_in_progress_bead_for_replacement",
                side_effect=lambda **_kwargs: lifecycle_events.append("retain") or True,
            )
        )
        claim_for_launch = stack.enter_context(
            patch.object(
                run_agent_runner_launch,
                "claim_bead_for_agent_launch",
                side_effect=lambda **_kwargs: lifecycle_events.append("promote"),
            )
        )

        def execute(*_args: object, **_kwargs: object) -> object:
            lifecycle_events.append("execute")
            meta = json.loads(
                (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
            )
            if bead_id is not None:
                assert meta["bead_claim_promoted"] is True
                assert not (artifacts_dir / BEAD_CLAIM_MARKER).exists()
            return exec_result

        run_execution_loop = stack.enter_context(
            patch.object(
                run_agent_runner_launch,
                "run_execution_loop",
                side_effect=execute,
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
        "claim_for_launch": claim_for_launch,
        "claim_for_wait": claim_for_wait,
        "lifecycle_events": lifecycle_events,
        "notify": notify,
        "retain_for_replacement": retain_for_replacement,
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
    assert wait_for_dependencies.call_args.kwargs["wait_beads"] == ["sase-87.2"]

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
        submitted_xprompt="%i(reviewer, family=foo)\nDo work",
    )


def test_waiting_bead_claims_before_wait_and_promotes_before_execution(
    tmp_path: Path,
) -> None:
    result = _run_runner_with_wait_result(
        tmp_path,
        None,
        bead_id="sase-87.2",
    )

    assert result["lifecycle_events"] == ["claim", "wait", "promote", "execute"]
    claim_for_wait = result["claim_for_wait"]
    assert isinstance(claim_for_wait, MagicMock)
    claim_for_wait.assert_called_once_with(
        project_name="sase",
        bead_id="sase-87.2",
        agent_name="foo--reviewer",
    )
    claim_for_launch = result["claim_for_launch"]
    assert isinstance(claim_for_launch, MagicMock)
    claim_for_launch.assert_called_once()
    shutdown_states = result["shutdown_states"]
    assert isinstance(shutdown_states, list)
    assert shutdown_states[0].held_bead_claim_id is None


def test_force_reuse_bead_marker_retains_wait_claim_without_release_marker(
    tmp_path: Path,
) -> None:
    result = _run_runner_with_wait_result(
        tmp_path,
        None,
        bead_id="sase-87.2",
        force_reuse_marker={
            "owner_name": "foo--reviewer",
            "bead_id": "sase-87.2",
        },
    )

    assert result["lifecycle_events"] == ["retain", "wait", "promote", "execute"]
    claim_for_wait = result["claim_for_wait"]
    assert isinstance(claim_for_wait, MagicMock)
    claim_for_wait.assert_not_called()
    retain = result["retain_for_replacement"]
    assert isinstance(retain, MagicMock)
    retain.assert_called_once_with(
        project_name="sase",
        bead_id="sase-87.2",
        agent_name="foo--reviewer",
        prior_owner="foo--reviewer",
    )
    claim_for_launch = result["claim_for_launch"]
    assert isinstance(claim_for_launch, MagicMock)
    assert claim_for_launch.call_args.kwargs["force_reuse_prior_owner"] == (
        "foo--reviewer"
    )
    shutdown_states = result["shutdown_states"]
    assert isinstance(shutdown_states, list)
    assert shutdown_states[0].held_bead_claim_id is None
