"""Tests for deferred workspace handling in the agent runner."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult

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
        monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", "/stale/parent")

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

    def test_deferred_wait_prepares_claimed_workspace_after_wait(
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

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            assert_no_run_started_at()
            events.append("claim")
            return 3, str(real_ws)

        def prepare_ws(workspace_dir: str, *_args: Any, **_kwargs: Any) -> bool:
            assert_no_run_started_at()
            events.append(("prepare", workspace_dir))
            return True

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            meta = json.loads(meta_path.read_text())
            assert meta["run_started_at"] == ctx.agent_meta["run_started_at"]
            events.append(("run", ctx.workspace_num, ctx.workspace_dir))
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{RUNNER}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{RUNNER}.claim_deferred_workspace"] = claim_deferred
        patches[f"{SETUP}.prepare_workspace"] = prepare_ws
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
            "claim",
            ("prepare", str(real_ws)),
            ("run", 3, str(real_ws)),
        ]

    def test_home_mode_deferred_wait_keeps_directory_workspace(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        cd_workspace = tmp_path / "cd-target"
        cd_workspace.mkdir()
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
            side_effect=AssertionError("cd agents must not claim deferred workspaces")
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(
            patches,
            tmp_path,
            workspace_dir=cd_workspace,
            workspace_num="0",
            is_home_mode=True,
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["wait", ("run", 0, str(cd_workspace))]

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
