"""Publication-retry and diagnostic-redaction coverage for failed-close recovery.

Split from the landing-proof repair commit so the focused recovery test
modules stay under the toobig budget.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.sync import commit_failed_close_recovery
from sase.finalizers._failed_close_recovery_assess import (
    _RecoveryAssessment,
    build_recovery_note,
)
from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.commit_types import failed_result
from sase.finalizers.failed_close_recovery import (
    RECOVERY_OUTCOME_FILENAME,
    RECOVERY_REQUEST_FILENAME,
    STITCH_FAILED_NOTE_PREFIX,
    coordinate_failed_close_recovery,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives

from ._failed_close_recovery_helpers import (
    close_phase_with_plan,
    fail_stitch,
    machine_lane,
    prepare_commit_run,
    seed_git_store,
)
from .finalizers_protocol_harness_test_helpers import (
    run_controller,
    submit_commit,
)

__all__ = [
    "TestPublicationRetry",
    "TestRedactionAndDeclarationEvidence",
]


def _git_run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _seed_git_store_with_remote(root: Path, remote: Path) -> BeadProject:
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    project = seed_git_store(root)
    _git_run(root, "config", "user.name", "probe")
    _git_run(root, "config", "user.email", "probe@example.invalid")
    _git_run(root, "add", "-A")
    _git_run(root, "commit", "-m", "init beads", "--allow-empty")
    _git_run(root, "remote", "add", "origin", str(remote))
    _git_run(root, "push", "-u", "origin", "HEAD")
    return project


def _git_push_origin(beads_dir: Path) -> SimpleNamespace:
    from sase.bead._sync_git import find_git_root

    repo = find_git_root(beads_dir)
    assert repo is not None
    result = subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return SimpleNamespace(
            pushed=False,
            skipped_no_remote=False,
            error=result.stderr.strip() or "push failed",
        )
    return SimpleNamespace(pushed=True, skipped_no_remote=False, error=None)


def _recovery_events_in_repo(root: Path) -> int:
    events_root = root / "sdd" / "beads" / "events"
    if not events_root.is_dir():
        events_root = root / "beads" / "events"
    count = 0
    for path in events_root.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if (
                "completion_failure_recovered" in line
                or "CompletionFailureRecovered" in line
            ):
                count += 1
    return count


class TestPublicationRetry:
    def test_retry_commits_after_failed_recovery_store_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        remote = tmp_path / "remote.git"
        store_root = tmp_path / "beadstore"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with _seed_git_store_with_remote(store_root, remote) as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        commit_calls = {"n": 0}
        real_commit = commit_failed_close_recovery

        def flaky_commit(
            target: Path,
            run_id: str,
            *,
            already_locked: bool = False,
            operation_context: Any = None,
        ) -> bool:
            commit_calls["n"] += 1
            if commit_calls["n"] == 1:
                return False
            return real_commit(target, run_id, already_locked=already_locked)

        with machine_lane(monkeypatch, beads_dir):
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._commit_recovery_mutation",
                flaky_commit,
            )
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._push_recovery_mutation",
                _git_push_origin,
            )
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
            first = json.loads(
                (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
            )
            assert first["committed"] is False
            assert first["published"] is False
            failure = BuiltinCommitFinalizerError(
                "hook failed",
                result=failed_result("commit", "stitch_failed", "hook failed"),
                invoke_result=InvokeResult(content=""),
            )
            outcome = coordinate_failed_close_recovery(str(artifacts), failure=failure)
            assert outcome.attempted is True
            assert outcome.published is True
            assert commit_calls["n"] == 2
        clone = tmp_path / "remote-clone"
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
        assert _recovery_events_in_repo(clone) == 2
        with BeadProject(store_root) as project:
            phase = project.show(phase_id)
            failed_notes = [
                note
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1
            assert phase.close_history[0].reopened_via is not None

    def test_retry_after_push_failure_publishes_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        remote = tmp_path / "remote.git"
        store_root = tmp_path / "beadstore"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with _seed_git_store_with_remote(store_root, remote) as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        pushes = {"n": 0}

        def flaky_push(target: Path) -> SimpleNamespace:
            pushes["n"] += 1
            if pushes["n"] == 1:
                return SimpleNamespace(
                    pushed=False, skipped_no_remote=False, error="push refused"
                )
            return _git_push_origin(target)

        with machine_lane(monkeypatch, beads_dir):
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._push_recovery_mutation",
                flaky_push,
            )
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
            failure = BuiltinCommitFinalizerError(
                "hook failed",
                result=failed_result("commit", "stitch_failed", "hook failed"),
                invoke_result=InvokeResult(content=""),
            )
            outcome = coordinate_failed_close_recovery(str(artifacts), failure=failure)
            assert outcome.published is True
            assert pushes["n"] == 2
        clone = tmp_path / "remote-clone"
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
        assert _recovery_events_in_repo(clone) == 2
        with BeadProject(store_root) as project:
            failed_notes = [
                note
                for note in project.show(phase_id).notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1

    def test_successor_claim_before_retry_is_not_rewound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._commit_recovery_mutation",
                lambda *_args, **_kwargs: False,
            )
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
            with BeadProject(tmp_path / "beadstore") as project:
                project.claim_for_agent_launch(phase_id, "successor.agent")
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._commit_recovery_mutation",
                commit_failed_close_recovery,
            )
            failure = BuiltinCommitFinalizerError(
                "hook failed",
                result=failed_result("commit", "stitch_failed", "hook failed"),
                invoke_result=InvokeResult(content=""),
            )
            coordinate_failed_close_recovery(str(artifacts), failure=failure)
        with BeadProject(tmp_path / "beadstore") as project:
            claimed = project.show(phase_id)
            assert claimed.status == Status.IN_PROGRESS
            assert claimed.assignee == "successor.agent"
            failed_notes = [
                note
                for note in claimed.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1


class TestRedactionAndDeclarationEvidence:
    def test_synthetic_secrets_are_absent_from_durable_surfaces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = "ghp_synthetic_not_a_real_token_123"
        diagnostic = f"api_key={secret}\nhook failed near the end"
        assessment = _RecoveryAssessment(
            should_recover=True,
            reason="unlanded_repository_obligations",
            stitch_attempted=True,
            failure_code="stitch_failed",
            failure_message=diagnostic,
        )
        note = build_recovery_note(
            assessment,
            {"run_id": "run-1", "agent_name": "agent-1"},
            artifacts_dir=str(tmp_path / "artifacts"),
            evidence_locations=[str(tmp_path / "artifacts")],
        )
        assert secret not in note
        assert "api_key" not in note.lower() or "<redacted" in note
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)

        def secret_stitch(
            _repo: Any,
            _message: str,
            _excludes: tuple[str, ...],
            _context: object,
        ) -> StitchCommandResult:
            return StitchCommandResult(
                returncode=1, stderr=f"token={secret}\nhook failed\n"
            )

        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", secret_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError):
                run_controller(artifacts)
        request = json.loads(
            (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
        )
        outcome = json.loads(
            (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
        )
        journal = (artifacts / "finalizers" / "progress.jsonl").read_text(
            encoding="utf-8"
        )
        with BeadProject(tmp_path / "beadstore") as project:
            note_text = "\n".join(note.text for note in project.show(phase_id).notes)
        for surface in (request["note"], json.dumps(outcome), journal, note_text):
            assert secret not in surface

    def test_declaration_failure_ignores_foreign_message_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        message_dir = repo / ".sase" / "finalizers"
        message_dir.mkdir(parents=True)
        (message_dir / "commit-message-old.txt").write_text(
            "old run message\n", encoding="utf-8"
        )
        resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=str(artifacts)
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir

        def silent_provider(prompt: str, **_kwargs: object) -> InvokeResult:
            return InvokeResult(content="no declaration here")

        provider = MagicMock()
        provider.invoke.side_effect = silent_provider
        with machine_lane(monkeypatch, beads_dir):
            with pytest.raises(RuntimeError, match="declaration recovery failed"):
                run_controller(artifacts, provider)
        with BeadProject(tmp_path / "beadstore") as project:
            text = "\n".join(
                note.text
                for note in project.show(phase_id).notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            )
            assert "No stitch/message file was created" in text
            assert "commit-message-old.txt" not in text
