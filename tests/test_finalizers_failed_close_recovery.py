"""Failed-close recovery at the terminal finalizer boundary.

Two failing regressions (a close plus a before-commit failure, and a close
plus a declaration-recovery failure) use a real temporary bead store and the
finalizer harness. Controls cover success, retry, landing proofs, handoff,
clean completion, and publication failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.bead.model import IssueType, PhaseSize, Resolution, Status
from sase.bead.project import BeadProject
from sase.bead.sync import commit_failed_close_recovery, push_bead_work_launch
from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.commit_types import failed_result
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.failed_close_recovery import (
    RECOVERY_OUTCOME_FILENAME,
    RECOVERY_REQUEST_FILENAME,
    STITCH_FAILED_NOTE_PREFIX,
    _assess_terminal_failure,
    coordinate_failed_close_recovery,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives

from .finalizers_live_e2e_test_helpers import command_instance
from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    successful_stitch,
)


def _commit_config() -> FinalizerConfig:
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    return FinalizerConfig(
        defaults=("commit",),
        required=(),
        instances={"commit": commit},
        provenance={},
    )


def _use_config(monkeypatch: pytest.MonkeyPatch, config: FinalizerConfig) -> None:
    def loader() -> FinalizerConfig:
        return config

    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.config.load_finalizer_config", loader)


def _seed_git_store(root: Path) -> BeadProject:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "config", "user.name", "probe"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "probe@example.invalid"], cwd=root, check=True
    )
    return BeadProject.init(root)


def _close_phase_with_plan(project: BeadProject) -> tuple[str, str]:
    """Create a plan plus phase and close both with the harness run identity."""
    plan = project.create("Recovery plan", IssueType.PLAN, tier="epic")
    phase = project.create(
        "Recovery phase",
        IssueType.PHASE,
        parent_id=plan.id,
        size=PhaseSize.MEDIUM,
        created_by="probe",
    )
    project.close([phase.id], resolution=Resolution.DONE)
    project.close([plan.id], resolution=Resolution.DONE)
    return plan.id, phase.id


@contextmanager
def _machine_lane(monkeypatch: pytest.MonkeyPatch, beads_dir: Path) -> Iterator[None]:
    """Route the machine lane at a temporary bead store."""
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("test-user", "test_host"),
    )
    store = SimpleNamespace(project="test-recovery", beads_dir=beads_dir, context=None)

    @contextmanager
    def acquire(project: str, run_id: str) -> Iterator[Any]:
        assert project == "test-recovery"
        assert run_id == "run-1"
        yield store

    def commit(
        target: Path,
        run_id: str,
        *,
        already_locked: bool = False,
        operation_context: Any = None,
    ) -> bool:
        return commit_failed_close_recovery(
            target, run_id, already_locked=already_locked
        )

    monkeypatch.setattr(
        "sase.finalizers.failed_close_recovery._resolve_machine_project",
        lambda _artifacts: "test-recovery",
    )
    monkeypatch.setattr(
        "sase.finalizers.failed_close_recovery._acquire_recovery_store", acquire
    )
    monkeypatch.setattr(
        "sase.finalizers.failed_close_recovery._commit_recovery_mutation", commit
    )
    yield


def _prepare_commit_run(
    monkeypatch: pytest.MonkeyPatch, artifacts: Path, repo: Path
) -> None:
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_dirty(monkeypatch, repo, {"repos": (dirty_repo(repo),)})
    _use_config(monkeypatch, _commit_config())


def _recovery_journal_events(artifacts: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    journal = artifacts / "finalizers" / "progress.jsonl"
    if not journal.is_file():
        return events
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("event") == "failed_close_recovery":
            events.append(record)
    return events


def _fail_stitch(
    _repo: DirtyRepo,
    _message: str,
    _excludes: tuple[str, ...],
    _context: object,
) -> StitchCommandResult:
    return StitchCommandResult(returncode=1, stderr="hook failed\n")


class TestClosePlusBeforeCommitFailure:
    def test_recovery_reopens_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            plan_id, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.completion_failure is not None
            assert phase.completion_failure.run_id == "run-1"
            assert phase.completion_failure.failure_code == "stitch_failed"
            failed_notes = [
                note
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1
            text = failed_notes[0].text
            assert "run-1" in text
            assert "hook failed" in text
            ancestors = project.show(plan_id)
            assert ancestors.status == Status.OPEN

    def test_request_and_outcome_artifacts_persisted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError):
                run_controller(artifacts)
        request = json.loads(
            (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
        )
        assert request["run_id"] == "run-1"
        assert request["failure_code"] == "stitch_failed"
        assert request["note"].startswith(STITCH_FAILED_NOTE_PREFIX)
        outcome = json.loads(
            (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
        )
        assert outcome["attempted"] is True
        assert outcome["published"] is True
        assert outcome["publication_error"] == ""
        events = _recovery_journal_events(artifacts)
        assert len(events) == 1
        assert events[0]["published"] is True


class TestClosePlusDeclarationRecoveryFailure:
    def test_recovery_names_missing_stitch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=str(artifacts)
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir

        def silent_provider(prompt: str, **_kwargs: object) -> InvokeResult:
            return InvokeResult(content="no declaration here")

        provider = MagicMock()
        provider.invoke.side_effect = silent_provider
        with _machine_lane(monkeypatch, beads_dir):
            with pytest.raises(RuntimeError, match="declaration recovery failed"):
                run_controller(artifacts, provider)
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.completion_failure is not None
            assert phase.completion_failure.run_id == "run-1"
            failed_notes = [
                note
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1
            assert "No stitch/message file was created" in failed_notes[0].text
            assert "declaration recovery failed" in failed_notes[0].text.lower()


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
        _use_config(monkeypatch, _commit_config())
        calls: list[str] = []
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create",
            successful_stitch(artifacts, dirty, calls),
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
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
        _use_config(monkeypatch, _commit_config())
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
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
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
        _use_config(
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
            _record_landing_marker(artifacts, repo_arg)
            return StitchCommandResult(returncode=0, stdout="ok\n")

        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", landing_stitch
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
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
        _use_config(
            monkeypatch,
            FinalizerConfig(
                defaults=("boom",),
                required=(),
                instances={"boom": boom},
                provenance={},
            ),
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            resolve_and_persist_finalizer_plan(
                PromptDirectives(), artifacts_dir=str(artifacts)
            )
            with pytest.raises(RuntimeError):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase_id).status == Status.CLOSED
        assessment = _assess_terminal_failure(
            str(artifacts),
            failure_code="boom_failed",
            failure_message="boom",
        )
        assert assessment.should_recover is False
        assert assessment.reason == "no_repository_obligations"


def _record_landing_marker(artifacts: Path, repo: DirtyRepo) -> None:
    existing = artifacts / "commit_results.json"
    payload = (
        json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else []
    )
    payload.append(
        {
            "cwd": repo.path,
            "result": "ok",
            "run_id": "run-1",
            "commit_sha": "a" * 40,
            "commit_tree": "b" * 40,
        }
    )
    existing.write_text(json.dumps(payload), encoding="utf-8")


class TestLandingProofs:
    def _submit_two_repo_declaration(
        self, monkeypatch: pytest.MonkeyPatch, artifacts: Path, repos: tuple[Path, ...]
    ) -> None:
        prepare_agent_env(monkeypatch, artifacts, repos[0])
        patch_dirty(
            monkeypatch,
            repos[0],
            {
                "repos": tuple(
                    dirty_repo(repo, name=f"repo-{index}")
                    for index, repo in enumerate(repos)
                )
            },
        )
        _use_config(monkeypatch, _commit_config())
        submit_commit(artifacts)

    def test_partial_landing_recovers_and_names_unlanded_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        artifacts = tmp_path / "artifacts"
        self._submit_two_repo_declaration(monkeypatch, artifacts, (repo_a, repo_b))
        _record_landing_marker(artifacts, dirty_repo(repo_a, name="repo-0"))
        assessment = _assess_terminal_failure(
            str(artifacts),
            failure_code="stitch_failed",
            failure_message="hook failed",
        )
        assert assessment.should_recover is True
        by_name = {item.repo.name: item for item in assessment.repositories}
        assert by_name["repo-0"].landed is True
        assert by_name["repo-1"].landed is False
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                monkeypatch.setattr(
                    "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
                )
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            failed_notes = [
                note
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1
            assert str(repo_b) in failed_notes[0].text
            assert "repo-1" in failed_notes[0].text

    def test_exact_proof_matching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        artifacts = tmp_path / "artifacts"
        self._submit_two_repo_declaration(monkeypatch, artifacts, (repo_a, repo_b))

        def assess_with(markers: list[dict[str, Any]]) -> Any:
            (artifacts / "commit_results.json").write_text(
                json.dumps(markers), encoding="utf-8"
            )
            return _assess_terminal_failure(
                str(artifacts),
                failure_code="stitch_failed",
                failure_message="hook failed",
            )

        good = {
            "cwd": str(repo_a),
            "result": "ok",
            "run_id": "run-1",
            "commit_sha": "a" * 40,
            "commit_tree": "b" * 40,
        }
        # Marker for another repository proves nothing here.
        assessment = assess_with([{**good, "cwd": str(repo_b)}])
        assert assessment.should_recover is True
        # Marker from another run proves nothing here.
        assessment = assess_with([{**good, "run_id": "run-2"}])
        assert assessment.should_recover is True
        # An unpushed commit is not a landing.
        assessment = assess_with([{**good, "pushed": False}])
        assert assessment.should_recover is True
        assert "unpushed" in assessment.repositories[0].detail
        # A settled marker is not a landing.
        assessment = assess_with([{**good, "settled": True}])
        assert assessment.should_recover is True
        # The exact marker lands its repository but not the other one.
        assessment = assess_with([good])
        assert assessment.should_recover is True
        by_name = {item.repo.name: item for item in assessment.repositories}
        assert by_name["repo-0"].landed is True
        assert by_name["repo-1"].landed is False


class TestHandoffAndIdentity:
    def test_pending_handoff_skips_assessment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=str(artifacts)
        )
        (artifacts / PLAN_PENDING_MARKER).write_text("1\n", encoding="utf-8")
        assessment = _assess_terminal_failure(
            str(artifacts),
            failure_code="stitch_failed",
            failure_message="hook failed",
        )
        assert assessment.should_recover is False
        assert assessment.reason == "pending_handoff"

    def test_human_close_without_provenance_never_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
        )
        monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
        monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        with _seed_git_store(tmp_path / "beadstore") as project:
            plan = project.create("Human plan", IssueType.PLAN, tier="epic")
            phase = project.create(
                "Human phase",
                IssueType.PHASE,
                parent_id=plan.id,
                size=PhaseSize.MEDIUM,
                created_by="human",
            )
            project.close([phase.id], resolution=Resolution.DONE)
            project.close([plan.id], resolution=Resolution.DONE)
            beads_dir = project.beads_dir
        # A later agent run fails terminally; the human closes above carry
        # no provenance for it and must be left alone.
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        with _machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase.id).status == Status.CLOSED


class TestPublicationFailure:
    def test_failed_push_retains_diagnostic_and_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            monkeypatch.setattr(
                "sase.finalizers.failed_close_recovery._push_recovery_mutation",
                lambda _beads: SimpleNamespace(
                    pushed=False, skipped_no_remote=False, error="push refused"
                ),
            )
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        outcome = json.loads(
            (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
        )
        assert outcome["attempted"] is True
        assert outcome["published"] is False
        assert outcome["publication_error"] == "push refused"
        assert "retry" in outcome["error"]
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.completion_failure is not None

    def test_retry_after_publication_failure_finishes_without_duplicate_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = _close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            monkeypatch.setattr(
                "sase.finalizers.failed_close_recovery._push_recovery_mutation",
                lambda _beads: SimpleNamespace(
                    pushed=False, skipped_no_remote=False, error="push refused"
                ),
            )
            with pytest.raises(BuiltinCommitFinalizerError):
                run_controller(artifacts)
            # A later retry recovers nothing new but finishes publication
            # through the real push (the failure patch above is replaced).
            monkeypatch.setattr(
                "sase.finalizers.failed_close_recovery._push_recovery_mutation",
                lambda beads: push_bead_work_launch(Path(beads)),
            )
            failure = BuiltinCommitFinalizerError(
                "hook failed",
                result=failed_result("commit", "stitch_failed", "hook failed"),
                invoke_result=InvokeResult(content=""),
            )
            outcome = coordinate_failed_close_recovery(str(artifacts), failure=failure)
            assert outcome.attempted is True
            assert outcome.already_applied
            assert not outcome.recovered
            assert outcome.published is True
        with BeadProject(tmp_path / "beadstore") as project:
            failed_notes = [
                note
                for note in project.show(phase_id).notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1


class TestMultipleCloses:
    def test_every_run_close_is_recovered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        _prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", _fail_stitch
        )
        with _seed_git_store(tmp_path / "beadstore") as project:
            task = project.create(
                "Extra task",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            plan_id, phase_id = _close_phase_with_plan(project)
            project.close([task.id], resolution=Resolution.DONE)
            beads_dir = project.beads_dir
        with _machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(task.id).status == Status.OPEN
            assert project.show(phase_id).status == Status.OPEN
            assert project.show(plan_id).status == Status.OPEN
