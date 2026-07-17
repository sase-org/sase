"""Integration tests for runner bootstrap error recording."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import run_agent_runner
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV


def _runner_args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        cl_name="bootstrap-failure",
        project_file="/tmp/projects/sase/sase.sase",
        workspace_dir=str(tmp_path / "workspace"),
        output_path=str(tmp_path / "output.log"),
        workspace_num=7,
        workflow_name="ace(run)-260701_010202",
        prompt_file=str(tmp_path / "prompt.md"),
        timestamp="260701_010202",
        update_target="",
        project_name="sase",
        is_home_mode=False,
    )


def _runner_patches(
    stack: ExitStack,
    *,
    tmp_path: Path,
) -> tuple[Path, MagicMock, MagicMock, MagicMock]:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    args = _runner_args(tmp_path)

    stack.enter_context(
        patch.object(run_agent_runner, "parse_runner_args", return_value=args)
    )
    stack.enter_context(
        patch.object(run_agent_runner, "install_workspace_release_sigterm_handler")
    )
    stack.enter_context(
        patch.object(
            run_agent_runner,
            "setup_artifacts_directory",
            return_value=("sase", "20260701010202", str(artifacts_dir)),
        )
    )
    stack.enter_context(
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation"
        )
    )
    stack.enter_context(
        patch(
            "sase.axe.run_agent_runner_finalize."
            "update_agent_artifact_index_for_marker_mutation"
        )
    )
    stack.enter_context(patch.object(run_agent_runner, "init_telemetry"))
    stack.enter_context(patch.object(run_agent_runner, "register_flush_on_exit"))
    stack.enter_context(patch.object(run_agent_runner, "print_agent_start_banner"))
    stack.enter_context(
        patch.object(run_agent_runner, "format_agent_run_runtime", return_value="0s")
    )
    record_completion = stack.enter_context(
        patch.object(run_agent_runner, "record_completion_metrics")
    )
    finalize = stack.enter_context(
        patch.object(run_agent_runner, "finalize_runner_shutdown")
    )
    agent_kills = stack.enter_context(patch.object(run_agent_runner, "AGENT_KILLS"))
    return artifacts_dir, record_completion, finalize, agent_kills


def test_missing_prompt_records_failed_done_and_finalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    with ExitStack() as stack:
        artifacts_dir, record_completion, finalize, agent_kills = _runner_patches(
            stack,
            tmp_path=tmp_path,
        )

        with pytest.raises(SystemExit) as exc_info:
            run_agent_runner.main()

    assert exc_info.value.code == 1
    done = json.loads((artifacts_dir / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "failed"
    assert done["error"].startswith("FileNotFoundError:")
    assert "read_prompt_file" in done["traceback"]
    assert done["output_path"] == str(tmp_path / "output.log")

    meta = json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["output_path"] == str(tmp_path / "output.log")
    assert record_completion.call_args.kwargs["active_agent_started"] is False
    assert finalize.call_count == 1
    assert finalize.call_args.kwargs["state"].error_summary == done["error"]
    agent_kills.labels.assert_called_once_with(reason="error")


def test_preprocessing_failure_records_failed_done_and_finalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    args = _runner_args(tmp_path)
    Path(args.prompt_file).write_text("Do work", encoding="utf-8")
    with ExitStack() as stack:
        artifacts_dir, _, finalize, _ = _runner_patches(stack, tmp_path=tmp_path)
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "preprocess_prompt_xprompts",
                side_effect=RuntimeError("xprompt bootstrap failed"),
            )
        )

        with pytest.raises(SystemExit) as exc_info:
            run_agent_runner.main()

    assert exc_info.value.code == 1
    done = json.loads((artifacts_dir / "done.json").read_text(encoding="utf-8"))
    assert done["error"] == "RuntimeError: xprompt bootstrap failed"
    assert "preprocess_prompt_xprompts" in done["traceback"]
    assert finalize.call_count == 1


def test_refreshed_bootstrap_preserves_phase_launch_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    args = _runner_args(tmp_path)
    Path(args.prompt_file).write_text("Do phase work", encoding="utf-8")
    existing_meta = {
        "pid": 123,
        "output_path": "/tmp/old-output.log",
        "wait_completed_at": "2026-07-01T01:02:03+00:00",
        "sdd_plan_path": "sdd/plans/202607/epic.md",
        "epic_bead_id": "sase-6k",
        "phase_bead_id": "sase-6k.3",
        "plan_committed": True,
        "agent_family": "sase-6k",
        "agent_family_role": "phase",
        "agent_family_parallel": True,
        "parent_timestamp": "20260701000000",
    }

    with ExitStack() as stack:
        artifacts_dir, _, _, _ = _runner_patches(stack, tmp_path=tmp_path)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(existing_meta),
            encoding="utf-8",
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "preprocess_prompt_xprompts",
                side_effect=RuntimeError("stop after refreshed bootstrap"),
            )
        )

        with pytest.raises(SystemExit) as exc_info:
            run_agent_runner.main()

    assert exc_info.value.code == 1
    meta = json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))
    for key, value in existing_meta.items():
        if key not in {"pid", "output_path"}:
            assert meta[key] == value
    assert meta["pid"] == os.getpid()
    assert meta["output_path"] == str(tmp_path / "output.log")


def test_user_kill_during_bootstrap_preserves_exit_and_skips_error_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    args = _runner_args(tmp_path)
    Path(args.prompt_file).write_text("Do work", encoding="utf-8")
    with ExitStack() as stack:
        artifacts_dir, record_completion, finalize, _ = _runner_patches(
            stack,
            tmp_path=tmp_path,
        )
        stack.enter_context(
            patch.object(
                run_agent_runner,
                "preprocess_prompt_xprompts",
                side_effect=SystemExit(143),
            )
        )
        record_error = stack.enter_context(
            patch.object(run_agent_runner, "record_runner_error")
        )

        with pytest.raises(SystemExit) as exc_info:
            run_agent_runner.main()

    assert exc_info.value.code == 143
    assert not (artifacts_dir / "done.json").exists()
    record_error.assert_not_called()
    record_completion.assert_not_called()
    assert finalize.call_count == 1
    state = finalize.call_args.kwargs["state"]
    assert state.exec_outcome == "killed"
    assert state.suppress_completion_notification is True
