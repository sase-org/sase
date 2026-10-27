"""Landing-proof coverage for failed-close recovery.

Split from ``tests.test_finalizers_failed_close_recovery``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.finalizers._failed_close_recovery_assess import assess_terminal_failure
from sase.finalizers.commit import BuiltinCommitFinalizerError
from sase.finalizers.failed_close_recovery import STITCH_FAILED_NOTE_PREFIX

from ._failed_close_recovery_helpers import (
    close_phase_with_plan,
    commit_config,
    fail_stitch,
    machine_lane,
    record_landing_marker,
    seed_git_store,
    use_config,
)
from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
)

__all__ = ["TestLandingProofs"]


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
        use_config(monkeypatch, commit_config())
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
        record_landing_marker(artifacts, dirty_repo(repo_a, name="repo-0"))
        assessment = assess_terminal_failure(
            str(artifacts),
            failure_code="stitch_failed",
            failure_message="hook failed",
        )
        assert assessment.should_recover is True
        by_name = {item.repo.name: item for item in assessment.repositories}
        assert by_name["repo-0"].landed is True
        assert by_name["repo-1"].landed is False
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                monkeypatch.setattr(
                    "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
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
            return assess_terminal_failure(
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
