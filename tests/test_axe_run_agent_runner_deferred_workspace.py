"""Tests for deferred workspace handling in the agent runner."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult

from sase.axe.run_agent_repeat_stop import RepeatStopDecision
from sase.linked_repos import LinkedRepoResolution, _ResolvedLinkedRepo

from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    RUNNER,
    SETUP,
    base_patches,
    exec_result,
    run_main,
)


class TestDeferredWorkspacePreparation:
    def test_claim_deferred_workspace_claims_and_returns_real_workspace(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        workspace_dir = tmp_path / "ws7"
        release_mock = MagicMock()
        claim_mock = MagicMock(return_value=ClaimResult(success=True))

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
            patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
            patch("sase.running_field.claim_workspace", claim_mock),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            first_ws.return_value = 7
            ws_dir.return_value = (str(workspace_dir), None)

            workspace_num, actual_workspace_dir = claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert workspace_num == 7
        assert actual_workspace_dir == str(workspace_dir)
        release_mock.assert_called_once_with(
            str(tmp_path / "project.sase"), 0, "test-workflow", "test-cl"
        )
        claim_mock.assert_called_once()
        chdir_mock.assert_called_once_with(str(workspace_dir))

    def test_claim_deferred_workspace_sets_active_project_dir_on_chdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runner chdir must also rewrite SASE_ACTIVE_PROJECT_DIR."""
        from sase.axe.run_agent_phases import claim_deferred_workspace

        workspace_dir = tmp_path / "ws7"
        resolved_sdd = workspace_dir / ".custom-sdd"
        monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", "/stale/parent")
        monkeypatch.setenv("SASE_SDD_DIR", "/stale/sdd")
        monkeypatch.setattr(
            "sase.sdd.store.resolve_sdd_dir",
            lambda workspace, workspace_num: resolved_sdd,
        )

        with (
            patch("sase.running_field.release_workspace"),
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                return_value=7,
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch(
                "sase.running_field.claim_workspace",
                return_value=ClaimResult(success=True),
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
        ):
            claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert os.environ["SASE_ACTIVE_PROJECT_DIR"] == str(workspace_dir)
        assert os.environ["SASE_SDD_DIR"] == str(resolved_sdd)

    def test_claim_deferred_workspace_recomputes_linked_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace
        from sase.linked_repos import (
            LINKED_REPOS_JSON_ENV,
            SIBLING_REPOS_JSON_ENV,
            resolve_linked_repos_for_project,
        )

        workspace_dir = tmp_path / "ws7"
        primary = tmp_path / "sase"
        sibling = tmp_path / "sase-core"
        primary.mkdir()
        sibling.mkdir()
        project_file = tmp_path / "project.sase"
        project_file.write_text(f"WORKSPACE_DIR: {primary}\nNAME: main\n")
        linked_workspace = (
            primary.with_name("sase_7") / "sase" / "repos" / "linked" / "core"
        )
        linked_workspace.mkdir(parents=True)
        resolution = resolve_linked_repos_for_project(
            project_file=str(project_file),
            workspace_dir=str(workspace_dir),
            workspace_num=7,
            config={
                "workspace": {"root": "adjacent"},
                "linked_repos": [{"name": "core", "path": "../sase-core"}],
            },
            materialize=False,
        )
        monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "stale")

        with (
            patch("sase.running_field.release_workspace"),
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                return_value=7,
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch(
                "sase.running_field.claim_workspace",
                return_value=ClaimResult(success=True),
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
            patch(
                "sase.linked_repos.resolve_linked_repos_for_project",
                return_value=resolution,
            ),
        ):
            claim_deferred_workspace(
                str(project_file),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        # Canonical linked env plus the deprecated sibling alias are recomputed.
        assert os.environ["SASE_LINKED_REPO_CORE_DIR"] == str(linked_workspace)
        assert os.environ["SASE_SIBLING_REPO_CORE_DIR"] == str(linked_workspace)
        assert json.loads(os.environ[LINKED_REPOS_JSON_ENV])[0]["name"] == "core"
        assert json.loads(os.environ[SIBLING_REPOS_JSON_ENV])[0]["name"] == "core"

    def test_claim_deferred_workspace_retries_claim_race(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "2")
        release_mock = MagicMock()
        claim_mock = MagicMock(
            side_effect=[
                ClaimResult(success=False, error="claim race"),
                ClaimResult(success=True),
            ]
        )

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                side_effect=[7, 8],
            ) as first_ws,
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=[
                    (str(tmp_path / "ws7"), None),
                    (str(tmp_path / "ws8"), None),
                ],
            ),
            patch("sase.running_field.claim_workspace", claim_mock),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            workspace_num, actual_workspace_dir = claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert workspace_num == 8
        assert actual_workspace_dir == str(tmp_path / "ws8")
        assert first_ws.call_count == 2
        assert claim_mock.call_count == 2
        chdir_mock.assert_called_once_with(str(tmp_path / "ws8"))

    def test_claim_deferred_workspace_exhaustion_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "1")

        with (
            patch("sase.running_field.release_workspace"),
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                side_effect=[7, 8],
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=[
                    (str(tmp_path / "ws7"), None),
                    (str(tmp_path / "ws8"), None),
                ],
            ),
            patch(
                "sase.running_field.claim_workspace",
                return_value=ClaimResult(success=False, error="claim rejected"),
            ),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            with pytest.raises(SystemExit) as exc_info:
                claim_deferred_workspace(
                    str(tmp_path / "project.sase"),
                    "test-project",
                    "test-workflow",
                    "test-cl",
                    "20260316_120000",
                )

        assert exc_info.value.code == 1
        assert "Failed to claim a real workspace after dependencies completed" in (
            capsys.readouterr().err
        )
        chdir_mock.assert_not_called()

    @pytest.mark.parametrize(
        ("wait_info", "expected_runners", "expected_priority"),
        [
            (AGENT_INFO._replace(wait_runners=0), 0, None),
            (AGENT_INFO._replace(wait_priority=20), None, 20),
        ],
    )
    def test_runner_slot_only_deferred_wait_gates_then_claims_workspace(
        self,
        tmp_path: Path,
        wait_info: Any,
        expected_runners: int | None,
        expected_priority: int | None,
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        events: list[str] = []

        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )
        wait_for_dependencies = MagicMock()
        detect_repeat_stop = MagicMock(return_value=None)
        write_error = MagicMock()

        def wait_for_slot(*_args: Any, claim: Any, **kwargs: Any) -> str:
            assert kwargs["wait_runners"] == expected_runners
            assert kwargs["wait_priority"] == expected_priority
            events.append("gate")
            return claim()

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            events.append("claim")
            return 3, str(real_ws)

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            events.append("run")
            assert ctx.workspace_num == 3
            assert ctx.workspace_dir == str(real_ws)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_dependencies
        patches[f"{RUNNER}.detect_repeat_stop"] = detect_repeat_stop
        patches[f"{RUNNER}.wait_for_runner_slot"] = MagicMock(side_effect=wait_for_slot)
        patches[f"{RUNNER}.claim_deferred_workspace"] = MagicMock(
            side_effect=claim_deferred
        )
        patches[f"{RUNNER}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock(side_effect=run_loop)
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(
            patches,
            tmp_path,
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["gate", "claim", "run"]
        wait_for_dependencies.assert_not_called()
        detect_repeat_stop.assert_not_called()
        write_error.assert_not_called()

    def test_deferred_wait_gates_before_claim_and_prepares_claimed_workspace(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        events: list[Any] = []

        wait_info = AGENT_INFO._replace(wait_names=["dep"])
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )
        meta_path = Path(artifacts_dir) / "agent_meta.json"

        def assert_no_run_started_at() -> None:
            if meta_path.exists():
                assert "run_started_at" not in json.loads(meta_path.read_text())

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> None:
            assert_no_run_started_at()
            events.append("wait")

        def wait_for_slot(*_args: Any, claim: Any, **kwargs: Any) -> str:
            assert kwargs["wait_runners"] is None
            assert_no_run_started_at()
            events.append("gate")
            return claim()

        def assert_run_started_at() -> None:
            assert "run_started_at" in json.loads(meta_path.read_text())

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            assert_run_started_at()
            events.append("claim")
            return 3, str(real_ws)

        def prepare_ws(workspace_dir: str, *_args: Any, **_kwargs: Any) -> bool:
            assert_run_started_at()
            events.append(("prepare", workspace_dir))
            return True

        def refresh_linked_repos(*_args: Any, **_kwargs: Any) -> LinkedRepoResolution:
            assert_run_started_at()
            events.append("refresh-linked")
            return LinkedRepoResolution(
                repos=(
                    _ResolvedLinkedRepo(
                        name="core",
                        env_name="CORE",
                        primary_dir=str(tmp_path / "sase-core"),
                        workspace_dir=str(tmp_path / "sase-core_3"),
                        workspace_num=3,
                    ),
                )
            )

        def prepare_linked_repos(**kwargs: Any) -> None:
            assert_run_started_at()
            resolution = kwargs["resolution"]
            events.append(("prepare-linked", resolution.repos[0].workspace_dir))

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            meta = json.loads(meta_path.read_text())
            assert meta["run_started_at"] == ctx.agent_meta["run_started_at"]
            events.append(("run", ctx.workspace_num, ctx.workspace_dir))
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{RUNNER}.wait_for_runner_slot"] = wait_for_slot
        patches[f"{RUNNER}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{RUNNER}.claim_deferred_workspace"] = claim_deferred
        patches[f"{SETUP}.prepare_workspace"] = prepare_ws
        patches[f"{RUNNER}.refresh_linked_repos_for_workspace"] = refresh_linked_repos
        patches[f"{RUNNER}.prepare_linked_repo_workspaces_if_needed"] = (
            prepare_linked_repos
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == [
            "wait",
            "gate",
            "claim",
            ("prepare", str(real_ws)),
            "refresh-linked",
            ("prepare-linked", str(tmp_path / "sase-core_3")),
            ("run", 3, str(real_ws)),
        ]

    def test_combined_wait_runs_dependencies_then_gate_then_claim(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        events: list[str] = []

        wait_info = AGENT_INFO._replace(wait_names=["dep"], wait_runners=1)
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> None:
            events.append("wait")

        def wait_for_slot(*_args: Any, claim: Any, **kwargs: Any) -> str:
            assert kwargs["wait_runners"] == 1
            events.append("gate")
            return claim()

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            events.append("claim")
            return 3, str(real_ws)

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            events.append("run")
            assert ctx.workspace_num == 3
            assert ctx.workspace_dir == str(real_ws)
            return exec_result(artifacts_dir)

        wait_for_dependencies = MagicMock(side_effect=wait_for_deps)
        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_dependencies
        patches[f"{RUNNER}.detect_repeat_stop"] = MagicMock(return_value=None)
        patches[f"{RUNNER}.wait_for_runner_slot"] = MagicMock(side_effect=wait_for_slot)
        patches[f"{RUNNER}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{RUNNER}.claim_deferred_workspace"] = MagicMock(
            side_effect=claim_deferred
        )
        patches[f"{RUNNER}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{RUNNER}.run_execution_loop"] = MagicMock(side_effect=run_loop)

        run_main(
            patches,
            tmp_path,
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["wait", "gate", "claim", "run"]
        wait_for_dependencies.assert_called_once()
        assert wait_for_dependencies.call_args.args[0] == ["dep"]

    def test_home_mode_deferred_wait_keeps_directory_workspace(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        direct_workspace = tmp_path / "direct-target"
        direct_workspace.mkdir()
        events: list[Any] = []

        wait_info = AGENT_INFO._replace(wait_duration=0.0)
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> None:
            events.append("wait")

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            events.append(("run", ctx.workspace_num, ctx.workspace_dir))
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{RUNNER}.claim_deferred_workspace"] = MagicMock(
            side_effect=AssertionError(
                "home-mode agents must not claim deferred workspaces"
            )
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            workspace_dir=direct_workspace,
            workspace_num="0",
            is_home_mode=True,
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["wait", ("run", 0, str(direct_workspace))]

    def test_repeat_stop_exits_before_workspace_claim_and_run_loop(
        self, tmp_path: Path
    ) -> None:
        """A repeat STOP after the wait skips the deferred claim and execution.

        Output variables must be written before the done marker, and the run
        must finish successfully with its completion notification suppressed.
        """
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        placeholder_ws.mkdir()
        order: list[str] = []

        wait_info = AGENT_INFO._replace(wait_names=["foo.1"])
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )
        patches[f"{RUNNER}.wait_for_dependencies"] = MagicMock()
        patches[f"{RUNNER}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{RUNNER}.detect_repeat_stop"] = MagicMock(
            return_value=RepeatStopDecision(producer_name="foo.1", stop_value="1")
        )
        gate_mock = patches[f"{RUNNER}.wait_for_runner_slot"]

        set_vars_mock = MagicMock(side_effect=lambda *a, **k: order.append("set_vars"))
        write_done_mock = MagicMock(
            side_effect=lambda *a, **k: order.append("write_done")
        )
        patches[f"{RUNNER}.set_agent_output_variables"] = set_vars_mock
        patches[f"{RUNNER}.write_done_marker_and_update_index"] = write_done_mock

        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        claim_mock = MagicMock(
            side_effect=AssertionError("stopped slot must not claim a workspace")
        )
        patches[f"{RUNNER}.claim_deferred_workspace"] = claim_mock

        notify_mock = MagicMock()
        patches[f"{RUNNER}.send_completion_notification"] = notify_mock
        patches[f"{RUNNER}.all_steps_hidden"] = MagicMock(return_value=False)

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        run_loop.assert_not_called()
        gate_mock.assert_not_called()
        claim_mock.assert_not_called()
        # Output variables are propagated before the completed done marker.
        assert order == ["set_vars", "write_done"]
        set_vars_mock.assert_called_once_with(artifacts_dir, {"STOP": "1"})
        # The done marker is a completed, repeat-stopped slot.
        done_marker = write_done_mock.call_args.args[1]
        assert done_marker["outcome"] == "completed"
        assert done_marker["repeat_stopped"] is True
        assert done_marker["stopped_by"] == "foo.1"
        # Completion notification is suppressed for a stopped slot.
        notify_mock.assert_not_called()

    def test_deferred_workspace_without_extracted_wait_fails_before_run_loop(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        placeholder_ws.mkdir()
        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        write_error = MagicMock()

        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(
                wait_names=[],
                wait_duration=None,
                wait_until=None,
                wait_runners=None,
            )
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        run_loop.assert_not_called()
        assert (
            "SASE_AGENT_DEFERRED_WORKSPACE=1" in write_error.call_args.kwargs["error"]
        )
