"""Failed-close snapshot evidence and relaunch recovery integration coverage."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.finalizers.commit import BuiltinCommitFinalizerError
from sase.finalizers.commit_types import failed_result
from sase.finalizers.failed_close_recovery import (
    RECOVERY_OUTCOME_FILENAME,
    RECOVERY_REQUEST_FILENAME,
    STITCH_FAILED_NOTE_PREFIX,
    coordinate_failed_close_recovery,
)
from sase.finalizers.config import FinalizerConfig
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives
from tests._failed_close_recovery_helpers import (
    close_phase_with_plan,
    commit_config,
    fail_stitch,
    machine_lane,
    prepare_commit_run,
    seed_git_store,
    use_config,
)
from tests.finalizers_live_e2e_test_helpers import (
    command_instance,
    submit_deferral_from_context,
)
from tests.finalizers_protocol_harness_test_helpers import run_controller, submit_commit
from tests.workspace_provider.test_rescue._helpers import git, redirect_state


def _init_repo(path: Path) -> None:
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "snapshot probe")
    git(path, "config", "user.email", "snapshot@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    for rel, payload in (
        ("dispatch.py", b"dispatch base\n"),
        ("docs/runner.md", b"runner docs base\n"),
        ("assets/data.bin", b"\x00base\xff"),
    ):
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    git(path, "add", "-A")
    git(path, "commit", "-m", "base")
    git(path, "remote", "add", "origin", "https://example.invalid/repo.git")


def _failure() -> BuiltinCommitFinalizerError:
    return BuiltinCommitFinalizerError(
        "hook failed",
        result=failed_result("commit", "stitch_failed", "hook failed"),
        invoke_result=InvokeResult(content=""),
    )


def _failure_manifest(request: dict[str, object]) -> Path:
    locations = request["snapshot_locations"]
    assert isinstance(locations, list) and len(locations) == 1
    manifest = Path(str(locations[0]))
    assert manifest.is_absolute() and manifest.is_file()
    return manifest


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True
    ).stdout


def _restore(repo: Path, manifest: Path, destination: Path) -> None:
    subprocess.run(["git", "clone", "-q", str(repo), str(destination)], check=True)
    from sase.workspace_provider.snapshot import restore_git_snapshot

    restore_git_snapshot(manifest, destination)


class TestFailedCloseSnapshots:
    def test_relaunch_cleanup_restores_tracked_and_untracked_bytes_from_failure_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redirect_state(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "dispatch.py").write_bytes(b"dispatch changed\n")
        (repo / "docs" / "runner.md").write_bytes(b"runner docs changed\n")
        (repo / "src").mkdir()
        (repo / "src" / "implementation.py").write_bytes(b"new implementation\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_new.py").write_bytes(b"new test\n")

        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        snapshots = {"calls": 0}
        import sase.finalizers._failed_close_recovery_snapshots as snapshot_flow

        real_snapshot = snapshot_flow.snapshot_git_repo

        def count_snapshot(*args: object, **kwargs: object) -> object:
            snapshots["calls"] += 1
            return real_snapshot(*args, **kwargs)

        monkeypatch.setattr(snapshot_flow, "snapshot_git_repo", count_snapshot)
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
            request = json.loads(
                (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
            )
            manifest = _failure_manifest(request)
            assert snapshots["calls"] == 1
            assert manifest.as_posix() in request["evidence_locations"]

            retry = coordinate_failed_close_recovery(str(artifacts), failure=_failure())
            assert retry.attempted is True
            assert retry.snapshot_locations == [str(manifest)]
            assert snapshots["calls"] == 1
            retry_request = json.loads(
                (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
            )
            assert retry_request["snapshots"][0]["reused"] is True

        from sase.workflows.commit_utils.workspace import run_sase_hg_clean

        cleaned, error = run_sase_hg_clean(str(repo), "failed-close-relaunch")
        assert cleaned, error
        assert git(repo, "status", "--porcelain").stdout == ""
        restored = tmp_path / "restored"
        _restore(repo, manifest, restored)
        assert (restored / "dispatch.py").read_bytes() == b"dispatch changed\n"
        assert (restored / "docs" / "runner.md").read_bytes() == (
            b"runner docs changed\n"
        )
        assert (restored / "src" / "implementation.py").read_bytes() == (
            b"new implementation\n"
        )
        assert (restored / "tests" / "test_new.py").read_bytes() == b"new test\n"
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            note = next(
                note.text
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            )
            assert manifest.as_posix() in note
        outcome = json.loads(
            (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
        )
        assert outcome["snapshot_locations"] == [manifest.as_posix()]
        assert outcome["snapshot_errors"] == []

    def test_staged_binary_snapshot_remains_recoverable_after_cleanup_reset_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redirect_state(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "dispatch.py").write_bytes(b"dispatch modified\n")
        (repo / "docs" / "runner.md").write_bytes(b"docs staged\n")
        git(repo, "add", "--", "docs/runner.md")
        staged_binary = b"\x00staged\xfe"
        worktree_binary = b"\x00worktree\xfd"
        (repo / "assets" / "data.bin").write_bytes(staged_binary)
        git(repo, "add", "--", "assets/data.bin")
        (repo / "assets" / "data.bin").write_bytes(worktree_binary)
        (repo / "src").mkdir()
        (repo / "src" / "untracked.bin").write_bytes(b"\x00untracked\xff")

        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        request = json.loads(
            (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
        )
        manifest = _failure_manifest(request)

        from sase.workflows.commit_utils import workspace as workspace_module

        def reset_then_fail(_name: str, _cwd: str) -> tuple[bool, str]:
            git(repo, "reset", "--hard", "HEAD")
            git(repo, "clean", "-fd")
            return False, "injected cleanup reset failure"

        monkeypatch.setattr(
            workspace_module,
            "get_vcs_provider",
            lambda _cwd: SimpleNamespace(stash_and_clean=reset_then_fail),
        )
        from sase.workflows.commit_utils.workspace import run_sase_hg_clean

        cleaned, error = run_sase_hg_clean(str(repo), "failed-close-reset-failure")
        assert cleaned is False
        assert error == "injected cleanup reset failure"
        assert git(repo, "status", "--porcelain").stdout == ""

        restored = tmp_path / "restored"
        _restore(repo, manifest, restored)
        assert (restored / "dispatch.py").read_bytes() == b"dispatch modified\n"
        assert (restored / "docs" / "runner.md").read_bytes() == b"docs staged\n"
        assert _git_bytes(restored, "show", ":assets/data.bin") == staged_binary
        assert (restored / "assets" / "data.bin").read_bytes() == worktree_binary
        assert (restored / "src" / "untracked.bin").read_bytes() == b"\x00untracked\xff"
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.OPEN

    def test_snapshot_failure_is_recorded_without_suppressing_reopen_or_cleanup_guard(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redirect_state(tmp_path, monkeypatch)
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "dispatch.py").write_bytes(b"unsaved dispatch\n")
        (repo / "src").mkdir()
        (repo / "src" / "implementation.py").write_bytes(b"unsaved source\n")
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        before = git(repo, "status", "--porcelain").stdout
        from sase.workspace_provider.snapshot import PreservationError

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise PreservationError("injected incomplete snapshot")

        monkeypatch.setattr(
            "sase.finalizers._failed_close_recovery_snapshots.snapshot_git_repo",
            refuse,
        )
        monkeypatch.setattr(
            "sase.workspace_provider.snapshot.snapshot_git_repo", refuse
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        request = json.loads(
            (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
        )
        assert request["snapshot_locations"] == []
        assert "injected incomplete snapshot" in request["snapshot_errors"][0]["error"]
        assert "Verified snapshot unavailable" in request["note"]

        from sase.workflows.commit_utils.workspace import run_sase_hg_clean

        cleaned, error = run_sase_hg_clean(str(repo), "refuse-unsafe-clean")
        assert cleaned is False
        assert "verified preservation failed" in error
        assert git(repo, "status", "--porcelain").stdout == before
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.OPEN

    def test_deferred_repository_followup_failure_does_not_snapshot_or_reopen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        base = commit_config()
        commit = base.instances["commit"]
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
        import sase.finalizers._failed_close_recovery_snapshots as snapshot_flow

        def unexpected_snapshot(*_args: object, **_kwargs: object) -> None:
            pytest.fail("deferred repository must not be snapshotted")

        monkeypatch.setattr(snapshot_flow, "snapshot_git_repo", unexpected_snapshot)
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            resolve_and_persist_finalizer_plan(
                PromptDirectives(), artifacts_dir=str(artifacts)
            )
            submit_deferral_from_context(
                artifacts, reason="foreign_work", paths=["src/app.py"]
            )
            with pytest.raises(RuntimeError):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.CLOSED
        assert not (artifacts / RECOVERY_REQUEST_FILENAME).exists()
