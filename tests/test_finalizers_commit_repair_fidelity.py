"""Coverage for truthful stitch failure messages and attempt fingerprinting.

See bead sase-ti.5: a stitch failure must surface the VCS provider's real
reason (whichever stream carried it), and a retry must not spend a mutating
attempt repeating an identical, guaranteed-to-fail dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.runner_reporting import write_error_report
from sase.finalizers.bounded_subprocess import BoundedCompletedProcess
from sase.finalizers.commit_repair import (
    load_latest_stitch_attempt,
    record_stitch_artifacts,
    run_stitch_create,
    run_stitch_resume,
    stitch_attempt_fingerprint,
    stitch_attempt_input_fields,
    stitch_failure_message,
)
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_types import DirtyRepo


def _repo(path: Path, name: str = "main") -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=("src/app.py",),
        kind="main",
    )


def test_stitch_failure_message_includes_both_streams(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = StitchCommandResult(
        returncode=1,
        stdout="❌ create_commit failed: No staged changes to commit\n",
        stderr=(
            "Commit message preserved at ... re-run with the same -M flag "
            "after fixing\n"
        ),
    )

    message = stitch_failure_message(repo, result)

    assert "No staged changes to commit" in message
    assert "re-run with the same -M flag" in message


def test_stitch_failure_message_bounds_long_streams(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = StitchCommandResult(returncode=1, stdout="x" * 10_000)

    message = stitch_failure_message(repo, result)

    assert len(message) < 10_000
    assert "truncated" in message


def test_stitch_failure_message_falls_back_to_exit_code_when_silent(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    result = StitchCommandResult(returncode=17)

    message = stitch_failure_message(repo, result)

    assert message == f"sase stitch create failed for {repo.name} with exit 17"


def test_error_report_carries_enriched_stitch_failure_message(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = StitchCommandResult(
        returncode=1,
        stdout="create_commit failed: No staged changes to commit\n",
        stderr="re-run with the same -M flag after fixing\n",
    )
    message = stitch_failure_message(repo, result)

    report_path = write_error_report(
        str(tmp_path),
        agent_model=None,
        agent_llm_provider=None,
        workflow_name="commit",
        cl_name="test",
        duration="1s",
        error_summary=message,
        error_traceback=None,
    )

    assert report_path is not None
    rendered = Path(report_path).read_text(encoding="utf-8")
    assert "No staged changes to commit" in rendered
    assert "re-run with the same -M flag" in rendered


def test_stitch_attempt_fingerprint_is_stable_for_identical_inputs(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    first = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(repo, "fix(final): reconcile", ("a.md",))
    )
    second = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(repo, "fix(final): reconcile", ("a.md",))
    )

    assert first == second


def test_stitch_attempt_fingerprint_changes_with_message(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    first = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(repo, "fix(final): reconcile", ())
    )
    second = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(repo, "fix(final): different message", ())
    )

    assert first != second


def test_stitch_attempt_fingerprint_changes_with_excludes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    first = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(repo, "fix(final): reconcile", ())
    )
    second = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(repo, "fix(final): reconcile", ("a.md",))
    )

    assert first != second


def test_stitch_attempt_fingerprint_changes_with_assigned_bead(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    first = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(
            repo,
            "fix(final): reconcile",
            (),
            assigned_bead_id="sase-zq.1",
        )
    )
    second = stitch_attempt_fingerprint(
        stitch_attempt_input_fields(
            repo,
            "fix(final): reconcile",
            (),
            assigned_bead_id="sase-zq.2",
        )
    )

    assert first != second


def test_run_stitch_create_binds_saved_assigned_bead_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo = _repo(repo_path)
    artifacts = tmp_path / "artifacts"
    captured: list[dict[str, str]] = []

    def fake_run_bounded_subprocess(
        _argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        input_bytes: bytes | None,
        timeout: float,
    ) -> BoundedCompletedProcess:
        del cwd, input_bytes, timeout
        captured.append(dict(env))
        return BoundedCompletedProcess(
            returncode=0,
            stdout=b"",
            stderr=b"",
            duration_seconds=0.01,
        )

    monkeypatch.setenv("SASE_BEAD_ID", "sase-ambient.9")
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.run_bounded_subprocess",
        fake_run_bounded_subprocess,
    )

    run_stitch_create(
        repo,
        "fix(final): reconcile",
        (),
        FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest=None,
            assigned_bead_id="sase-accepted.1",
        ),
        bead_action="keep",
    )

    assert captured[0]["SASE_BEAD_ID"] == "sase-accepted.1"


def test_run_stitch_resume_clears_ambient_bead_when_context_is_unbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo = _repo(repo_path)
    captured: list[dict[str, str]] = []

    def fake_run_bounded_subprocess(
        _argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        input_bytes: bytes | None,
        timeout: float,
    ) -> BoundedCompletedProcess:
        del cwd, input_bytes, timeout
        captured.append(dict(env))
        return BoundedCompletedProcess(
            returncode=0,
            stdout=b"",
            stderr=b"",
            duration_seconds=0.01,
        )

    monkeypatch.setenv("SASE_BEAD_ID", "sase-ambient.9")
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.run_bounded_subprocess",
        fake_run_bounded_subprocess,
    )

    run_stitch_resume(
        repo,
        FinalizerExecutionContext(artifacts_dir=None, plan_digest=None),
        bead_action="keep",
    )

    assert "SASE_BEAD_ID" not in captured[0]


def test_record_and_load_latest_stitch_attempt_round_trip(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    context = FinalizerExecutionContext(artifacts_dir=str(artifacts), plan_digest=None)
    repo = _repo(tmp_path / "repo")
    fields = stitch_attempt_input_fields(repo, "fix(final): reconcile", ("a.md",))
    fingerprint = stitch_attempt_fingerprint(fields)
    result = StitchCommandResult(returncode=1, stderr="hook failed\n")

    record_stitch_artifacts(
        context,
        "commit",
        1,
        result,
        label=repo.name,
        inputs={**fields, "fingerprint": fingerprint},
    )

    prior = load_latest_stitch_attempt(context, "commit", repo.name)

    assert prior is not None
    assert prior.attempt == 1
    assert prior.inputs["fingerprint"] == fingerprint
    assert prior.stderr == "hook failed\n"
    assert prior.outcome is not None
    assert prior.outcome["returncode"] == 1
    assert prior.outcome["timed_out"] is False


def test_load_latest_stitch_attempt_picks_the_highest_attempt(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    context = FinalizerExecutionContext(artifacts_dir=str(artifacts), plan_digest=None)
    repo = _repo(tmp_path / "repo")

    for attempt, stderr in ((1, "first failure\n"), (2, "second failure\n")):
        fields = stitch_attempt_input_fields(repo, f"fix(final): attempt {attempt}", ())
        record_stitch_artifacts(
            context,
            "commit",
            attempt,
            StitchCommandResult(returncode=1, stderr=stderr),
            label=repo.name,
            inputs={**fields, "fingerprint": stitch_attempt_fingerprint(fields)},
        )

    prior = load_latest_stitch_attempt(context, "commit", repo.name)

    assert prior is not None
    assert prior.attempt == 2
    assert prior.stderr == "second failure\n"


def test_load_latest_stitch_attempt_returns_none_without_prior_record(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    context = FinalizerExecutionContext(artifacts_dir=str(artifacts), plan_digest=None)

    assert load_latest_stitch_attempt(context, "commit", "main") is None
