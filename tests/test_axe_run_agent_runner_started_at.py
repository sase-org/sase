"""Tests for runner run_started_at recording."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from sase.linked_repos import LinkedRepoResolution, _ResolvedLinkedRepo

from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    RUNNER,
    SETUP,
    base_patches,
    exec_result,
    run_main,
)


class TestRunStartedAtRecording:
    def test_agent_meta_is_published_before_workspace_preparation(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        patches = base_patches(artifacts_dir)
        events: list[str] = []
        meta_path = Path(artifacts_dir) / "agent_meta.json"

        def extract_and_write_meta(
            _prompt: str,
            workspace_dir_arg: str,
            artifacts_dir_arg: str,
            **_kwargs: Any,
        ) -> Any:
            assert artifacts_dir_arg == artifacts_dir
            assert Path.cwd() == workspace_dir
            meta = {
                "pid": 1,
                "workspace_dir": workspace_dir_arg,
                "name": "test-agent",
                "model": "test-model",
                "llm_provider": "test-provider",
            }
            meta_path.write_text(json.dumps(meta))
            events.append("meta")
            return AGENT_INFO._replace(meta=meta)

        def prepare_workspace(
            workspace_dir_arg: str, *_args: Any, **_kwargs: Any
        ) -> bool:
            assert workspace_dir_arg == str(workspace_dir)
            meta = json.loads(meta_path.read_text())
            assert meta["name"] == "test-agent"
            assert "run_started_at" not in meta
            events.append("prepare")
            return True

        def run_loop(_ctx: Any, _prompt: str) -> Any:
            events.append("run")
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.extract_directives_and_write_meta"] = extract_and_write_meta
        patches[f"{SETUP}.prepare_workspace"] = prepare_workspace
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=workspace_dir,
        )

        assert events == ["meta", "prepare", "run"]

    def test_no_wait_runner_records_run_started_at_before_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        seen_run_started_at: list[str] = []

        def run_loop(ctx: Any, _prompt: str) -> Any:
            meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
            run_started_at = meta.get("run_started_at")
            assert isinstance(run_started_at, str)
            assert run_started_at == ctx.agent_meta["run_started_at"]
            seen_run_started_at.append(run_started_at)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        assert len(seen_run_started_at) == 1

    def test_runner_persists_sdd_base_sha_before_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        seen: list[str] = []

        def run_loop(ctx: Any, _prompt: str) -> Any:
            meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
            assert meta["sdd_base_sha"] == "abc123"
            assert ctx.agent_meta["sdd_base_sha"] == "abc123"
            seen.append(meta["sdd_base_sha"])
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.capture_sdd_base_sha"] = MagicMock(return_value="abc123")
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        assert seen == ["abc123"]

    def test_runner_populates_multi_agent_prompt_file_from_env(
        self,
        tmp_path: Path,
    ) -> None:
        from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_FILE_ENV

        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        seen: list[str | None] = []

        def run_loop(ctx: Any, _prompt: str) -> Any:
            seen.append(ctx.multi_agent_prompt_file)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            env={MULTI_AGENT_PROMPT_FILE_ENV: ("~/.sase/multi_prompts/202606/main.md")},
        )

        assert seen == ["~/.sase/multi_prompts/202606/main.md"]

    def test_error_after_slot_admission_records_run_started_at(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        run_loop = MagicMock()
        patches[f"{RUNNER}.resolve_agent_refs_in_prompt"] = MagicMock(
            side_effect=RuntimeError("bad agent ref")
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        run_loop.assert_not_called()
        meta_path = artifacts_dir / "agent_meta.json"
        run_started_at = json.loads(meta_path.read_text()).get("run_started_at")
        assert isinstance(run_started_at, str)

    def test_linked_repo_prep_failure_stops_before_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        workspace_dir = tmp_path / "workspace"
        linked_workspace_dir = tmp_path / "sase-core_7"
        workspace_dir.mkdir()
        linked_workspace_dir.mkdir()
        patches = base_patches(str(artifacts_dir))
        run_loop = MagicMock()
        write_error = MagicMock()

        def refresh_linked_repos_for_workspace(
            *_args: Any, **_kwargs: Any
        ) -> LinkedRepoResolution:
            return LinkedRepoResolution(
                repos=(
                    _ResolvedLinkedRepo(
                        name="core",
                        env_name="CORE",
                        primary_dir=str(tmp_path / "sase-core"),
                        workspace_dir=str(linked_workspace_dir),
                        workspace_num=7,
                        auto_clone=True,
                    ),
                )
            )

        def prepare_workspace(
            workspace_dir_arg: str, *_args: Any, **_kwargs: Any
        ) -> bool:
            return workspace_dir_arg == str(workspace_dir)

        patches[f"{RUNNER}.refresh_linked_repos_for_workspace"] = (
            refresh_linked_repos_for_workspace
        )
        patches[f"{SETUP}.prepare_workspace"] = prepare_workspace
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=workspace_dir,
            workspace_num="7",
        )

        run_loop.assert_not_called()
        assert (
            "Failed to materialize linked repo 'core' workspace"
            in (write_error.call_args.kwargs["error"])
        )
        meta_path = artifacts_dir / "agent_meta.json"
        if meta_path.exists():
            assert "run_started_at" not in json.loads(meta_path.read_text())

    def test_killed_while_waiting_does_not_record_run_started_at(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(wait_duration=1.0)
        )
        patches[f"{RUNNER}.wait_for_dependencies"] = MagicMock(
            side_effect=SystemExit(128 + 15)
        )
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock()

        run_main(patches, tmp_path)

        patches[f"{RUNNER}.run_execution_loop"].assert_not_called()
        meta_path = artifacts_dir / "agent_meta.json"
        if meta_path.exists():
            assert "run_started_at" not in json.loads(meta_path.read_text())

    def test_record_run_started_at_preserves_existing_timestamp(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import record_run_started_at

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        meta_path = artifacts_dir / "agent_meta.json"
        meta_path.write_text(
            json.dumps({"pid": 1, "run_started_at": "2026-05-12T12:00:00+00:00"})
        )
        agent_meta = {"pid": 1}

        recorded = record_run_started_at(str(artifacts_dir), agent_meta)

        assert recorded == "2026-05-12T12:00:00+00:00"
        assert agent_meta["run_started_at"] == "2026-05-12T12:00:00+00:00"
        assert json.loads(meta_path.read_text())["run_started_at"] == (
            "2026-05-12T12:00:00+00:00"
        )

    def test_runner_passes_recorded_run_started_at_to_runtime_formatter(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        record_run_started_at = MagicMock(return_value="2026-05-12T12:00:00+00:00")
        format_runtime = MagicMock(return_value="4m32s")
        notify = MagicMock()
        patches[f"{RUNNER}.record_run_started_at"] = record_run_started_at
        patches[f"{RUNNER}.format_agent_run_runtime"] = format_runtime
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock(
            return_value=exec_result(artifacts_dir)
        )
        patches[f"{RUNNER}.send_completion_notification"] = notify
        patches[f"{RUNNER}.all_steps_hidden"] = MagicMock(return_value=False)

        run_main(patches, tmp_path)

        format_runtime.assert_called_once()
        assert format_runtime.call_args.kwargs["launch_timestamp_suffix"] == (
            "20260316_120000"
        )
        assert format_runtime.call_args.kwargs["run_started_at"] == (
            "2026-05-12T12:00:00+00:00"
        )
        notify.assert_called_once()
        assert notify.call_args.kwargs["current_artifacts_dir"] == artifacts_dir
        assert notify.call_args.kwargs["runtime"] == "4m32s"

    def test_system_exit_from_execution_writes_failure_marker_and_notifies(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        write_error = MagicMock()
        notify = MagicMock()
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock(side_effect=SystemExit(1))
        patches[f"{RUNNER}.write_error_done_marker"] = write_error
        patches[f"{RUNNER}.send_completion_notification"] = notify
        patches[f"{RUNNER}.all_steps_hidden"] = MagicMock(return_value=False)

        run_main(patches, tmp_path)

        write_error.assert_called_once()
        assert write_error.call_args.kwargs["error"] == "SystemExit: 1"
        assert "SystemExit: 1" in write_error.call_args.kwargs["traceback_str"]
        notify.assert_called_once()
        assert notify.call_args.kwargs["success"] is False
        assert notify.call_args.kwargs["error_summary"] == "SystemExit: 1"

    def test_home_mode_running_marker_cleanup_updates_artifact_index(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        patches = base_patches(artifacts_dir)
        setup_index_update = MagicMock()
        cleanup_index_update = MagicMock()
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock(
            return_value=exec_result(artifacts_dir)
        )
        patches[
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation"
        ] = setup_index_update
        patches[f"{RUNNER}.update_agent_artifact_index_for_marker_mutation"] = (
            cleanup_index_update
        )

        run_main(patches, tmp_path, is_home_mode=True)

        assert not (Path(artifacts_dir) / "running.json").exists()
        assert setup_index_update.call_count == 2
        cleanup_index_update.assert_called_once_with(artifacts_dir)
