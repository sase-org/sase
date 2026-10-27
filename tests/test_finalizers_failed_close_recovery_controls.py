"""Success and retry controls for failed-close recovery.

Split from ``tests.test_finalizers_failed_close_recovery``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.finalizers._failed_close_recovery_assess import assess_terminal_failure
from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.failed_close_recovery import RECOVERY_REQUEST_FILENAME
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.macro.directives import PromptDirectives

from ._failed_close_recovery_helpers import (
    close_phase_with_plan,
    commit_config,
    machine_lane,
    record_landing_marker,
    seed_git_store,
    use_config,
)
from .finalizers_live_e2e_test_helpers import command_instance
from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    successful_stitch,
)

__all__ = ["TestControls"]


class TestControls:
    def test_success_leaves_close_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_agent_env(monkeypatch, artifacts, repo)
        dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
        patch_dirty(monkeypatch, repo, dirty)
        use_config(monkeypatch, commit_config())
        calls: list[str] = []
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create",
            successful_stitch(artifacts, dirty, calls),
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            result = run_controller(artifacts)
        assert result.content == "done"
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.CLOSED
        assert not (artifacts / RECOVERY_REQUEST_FILENAME).exists()

    def test_successful_retry_leaves_close_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_agent_env(monkeypatch, artifacts, repo)
        dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
        patch_dirty(monkeypatch, repo, dirty)
        use_config(monkeypatch, commit_config())
        calls = {"n": 0}

        def flaky_stitch(
            repo_arg: DirtyRepo,
            _message: str,
            _excludes: tuple[str, ...],
            _context: object,
        ) -> StitchCommandResult:
            calls["n"] += 1
            if calls["n"] == 1:
                submit_commit(artifacts, message="fix(final): retried message")
                return StitchCommandResult(returncode=1, stderr="hook failed\n")
            dirty["repos"] = tuple(
                item for item in dirty["repos"] if item.path != repo_arg.path
            )
            existing = artifacts / "commit_results.json"
            payload = (
                json.loads(existing.read_text(encoding="utf-8"))
                if existing.exists()
                else []
            )
            payload.append(
                {
                    "cwd": repo_arg.path,
                    "result": "ok",
                    "run_id": "run-1",
                    "commit_sha": "a" * 40,
                    "commit_tree": "b" * 40,
                }
            )
            existing.write_text(json.dumps(payload), encoding="utf-8")
            return StitchCommandResult(returncode=0, stdout="ok\n")

        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", flaky_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            result = run_controller(artifacts)
        assert result.content == "done"
        assert calls["n"] == 2
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.CLOSED
        assert not (artifacts / RECOVERY_REQUEST_FILENAME).exists()

    def test_landed_commit_plus_later_plugin_failure_leaves_close_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_agent_env(monkeypatch, artifacts, repo)
        patch_dirty(monkeypatch, repo, {"repos": (dirty_repo(repo),)})
        commit = ConfiguredFinalizerInstance(
            instance_id="commit",
            provider_ref="builtin@commit",
            max_attempts=2,
            provenance={"use": FinalizerFieldProvenance("test", None)},
        )
        boom = command_instance(
            "boom",
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            after=("commit",),
        )
        use_config(
            monkeypatch,
            FinalizerConfig(
                defaults=("commit", "boom"),
                required=(),
                instances={"commit": commit, "boom": boom},
                provenance={},
            ),
        )

        def landing_stitch(
            repo_arg: DirtyRepo,
            _message: str,
            _excludes: tuple[str, ...],
            _context: object,
        ) -> StitchCommandResult:
            record_landing_marker(artifacts, repo_arg)
            return StitchCommandResult(returncode=0, stdout="ok\n")

        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", landing_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(RuntimeError):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.CLOSED
        assert not (artifacts / RECOVERY_REQUEST_FILENAME).exists()

    def test_clean_completion_failure_leaves_close_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_agent_env(monkeypatch, artifacts, repo)
        patch_dirty(monkeypatch, repo, {"repos": ()})
        boom = command_instance(
            "boom",
            [sys.executable, "-c", "import sys; sys.exit(3)"],
        )
        use_config(
            monkeypatch,
            FinalizerConfig(
                defaults=("boom",),
                required=(),
                instances={"boom": boom},
                provenance={},
            ),
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            resolve_and_persist_finalizer_plan(
                PromptDirectives(), artifacts_dir=str(artifacts)
            )
            with pytest.raises(RuntimeError):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.CLOSED
        assessment = assess_terminal_failure(
            str(artifacts),
            failure_code="boom_failed",
            failure_message="boom",
        )
        assert assessment.should_recover is False
        assert assessment.reason == "no_repository_obligations"
