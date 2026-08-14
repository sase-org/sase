"""Tests for deferred workspace flow in the agent runner."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.axe.clan_summary_script import (
    POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL,
)
from sase.axe.run_agent_phases import ClanSummaryResolutionRequest
from sase.linked_repos import LinkedRepoResolution, _ResolvedLinkedRepo

from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    BOOTSTRAP,
    LAUNCH,
    RUNNER,
    SETUP,
    base_patches,
    exec_result,
    run_main,
)


class TestDeferredWorkspaceFlow:
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
        meta_path = Path(artifacts_dir) / "agent_meta.json"
        events: list[str] = []

        patches = base_patches(artifacts_dir)
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
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
            meta = json.loads(meta_path.read_text())
            assert meta["workspace_num"] == 3
            assert meta["workspace_dir"] == str(real_ws)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_dependencies
        patches[f"{RUNNER}.detect_repeat_stop"] = detect_repeat_stop
        patches[f"{RUNNER}.wait_for_runner_slot"] = MagicMock(side_effect=wait_for_slot)
        patches[f"{LAUNCH}.claim_deferred_workspace"] = MagicMock(
            side_effect=claim_deferred
        )
        patches[f"{LAUNCH}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{LAUNCH}.run_execution_loop"] = MagicMock(side_effect=run_loop)
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

        wait_info = AGENT_INFO._replace(
            wait_names=["dep"],
            bead_id="sase-8f.2",
            clan_summary_resolution=ClanSummaryResolutionRequest(
                script="./describe-clan",
                clan_name="sase-8f",
                clan_generation="generation-1",
                clan_tribe="epic",
            ),
        )
        patches = base_patches(artifacts_dir)
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )
        meta_path = Path(artifacts_dir) / "agent_meta.json"

        def assert_no_run_started_at() -> None:
            if meta_path.exists():
                assert "run_started_at" not in json.loads(meta_path.read_text())

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> bool:
            assert_no_run_started_at()
            events.append("wait")
            return True

        def refresh_code(*_args: Any, **kwargs: Any) -> None:
            assert kwargs["blocking_wait_occurred"] is True
            assert_no_run_started_at()
            events.append("refresh")

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

        def prepare_sidecars(workspace_dir: str, workspace_num: int) -> frozenset[str]:
            assert workspace_dir == str(real_ws)
            assert workspace_num == 3
            events.append("prepare-sidecars")
            return frozenset()

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

        def resolve_clan_summary(_script: str, **kwargs: Any) -> None:
            assert kwargs["workspace_dir"] == str(real_ws)
            assert kwargs["clan_name"] == "sase-8f"
            assert kwargs["clan_generation"] == "generation-1"
            assert kwargs["clan_tribe"] == "epic"
            assert kwargs["attempt_label"] == POST_WORKSPACE_PREPARATION_ATTEMPT_LABEL
            events.append("summary")

        def claim_bead(**kwargs: Any) -> None:
            assert_run_started_at()
            assert kwargs == {
                "agent_name": "test-agent",
                "bead_id": "sase-8f.2",
                "workspace_dir": str(real_ws),
                "workspace_num": 3,
                "artifacts_dir": artifacts_dir,
            }
            events.append("claim-bead")

        def capture_sdd(workspace_dir: str, workspace_num: int) -> None:
            assert workspace_dir == str(real_ws)
            assert workspace_num == 3
            events.append("capture-sdd")

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            meta = json.loads(meta_path.read_text())
            assert meta["run_started_at"] == ctx.agent_meta["run_started_at"]
            events.append(("run", ctx.workspace_num, ctx.workspace_dir))
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{RUNNER}.refresh_runner_code_after_wait"] = refresh_code
        patches[f"{RUNNER}.wait_for_runner_slot"] = wait_for_slot
        patches[f"{LAUNCH}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{LAUNCH}.claim_deferred_workspace"] = claim_deferred
        patches[f"{SETUP}.prepare_workspace"] = prepare_ws
        patches[f"{SETUP}.prepare_launch_workspace_repos"] = prepare_sidecars
        patches[f"{LAUNCH}.refresh_linked_repos_for_workspace"] = refresh_linked_repos
        patches[f"{LAUNCH}.prepare_linked_repo_workspaces_if_needed"] = (
            prepare_linked_repos
        )
        patches[f"{LAUNCH}.resolve_clan_summary_script"] = resolve_clan_summary
        patches[f"{LAUNCH}.claim_bead_for_agent_launch"] = claim_bead
        patches[f"{LAUNCH}.capture_sdd_base_sha"] = capture_sdd
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop

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
            "refresh",
            "gate",
            "claim",
            ("prepare", str(real_ws)),
            "prepare-sidecars",
            "refresh-linked",
            ("prepare-linked", str(tmp_path / "sase-core_3")),
            "summary",
            "claim-bead",
            "capture-sdd",
            ("run", 3, str(real_ws)),
        ]

    def test_incomplete_clan_fork_expands_after_wait_before_slot_and_claim(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        events: list[str] = []

        patches = base_patches(artifacts_dir)
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(wait_names=["review"])
        )

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> None:
            events.append("wait")

        def expand_fork(prompt: str, *_args: Any, **_kwargs: Any) -> str:
            assert events == ["wait"]
            events.append("fork")
            return prompt.replace("test prompt", "injected clan history")

        def wait_for_slot(*_args: Any, claim: Any, **_kwargs: Any) -> str:
            events.append("gate")
            return claim()

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            events.append("claim")
            return 3, str(real_ws)

        def run_loop(_ctx: Any, prompt: str) -> SimpleNamespace:
            events.append("run")
            assert prompt == "injected clan history"
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{RUNNER}.expand_deferred_launch_xprompts"] = expand_fork
        patches[f"{RUNNER}.wait_for_runner_slot"] = wait_for_slot
        patches[f"{LAUNCH}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{LAUNCH}.claim_deferred_workspace"] = claim_deferred
        patches[f"{LAUNCH}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["wait", "fork", "gate", "claim", "run"]

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
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
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
        patches[f"{LAUNCH}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{LAUNCH}.claim_deferred_workspace"] = MagicMock(
            side_effect=claim_deferred
        )
        patches[f"{LAUNCH}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{LAUNCH}.run_execution_loop"] = MagicMock(side_effect=run_loop)

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
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> None:
            events.append("wait")

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            events.append(("run", ctx.workspace_num, ctx.workspace_dir))
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{LAUNCH}.claim_deferred_workspace"] = MagicMock(
            side_effect=AssertionError(
                "home-mode agents must not claim deferred workspaces"
            )
        )
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            workspace_dir=direct_workspace,
            workspace_num="0",
            is_home_mode=True,
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["wait", ("run", 0, str(direct_workspace))]
