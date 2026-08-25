"""Controller cycle, conflict-resume, and fail-closed coverage for the finalizer protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import FinalizerControllerError
from sase.finalizers.declaration import FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT
from sase.xprompt.directives import PromptDirectives

from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    successful_stitch,
)


def test_successful_conflict_resume_continues_same_stitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        dirty["repos"] = ()
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": repo_arg.path,
                        "result": "ok",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(
        content="resolved",
        usage={"input_tokens": 4},
    )

    submit_commit(artifacts)
    result = run_controller(artifacts, provider)

    assert calls == ["create", "resume"]
    assert "resolved" in result.content
    assert result.usage == {"input_tokens": 4}
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    evidence_kinds = [
        item["kind"]
        for instance in payload["instances"]
        for item in instance.get("evidence", [])
    ]
    assert "conflict_repair" in evidence_kinds


@pytest.mark.parametrize("marker_matches_sidecar", [True, False])
def test_resumed_sidecar_row_is_matched_by_exact_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_matches_sidecar: bool,
) -> None:
    """A resumed sidecar row counts only when its cwd is that sidecar."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sidecar = tmp_path / "plans"
    sidecar.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(sidecar, name="plans", kind="sibling"),)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        dirty["repos"] = ()
        marker_cwd = str(sidecar) if marker_matches_sidecar else str(repo)
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": marker_cwd,
                        "result": "ok",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")

    submit_commit(artifacts)
    if marker_matches_sidecar:
        result = run_controller(artifacts, provider)
        assert calls == ["create", "resume"]
        assert "resolved" in result.content
        payload = json.loads((artifacts / "finalizer_result.json").read_text())
        assert payload["status"] == "success"
    else:
        with pytest.raises(
            BuiltinCommitFinalizerError,
            match="no commit_results.json entry was recorded",
        ):
            run_controller(artifacts, provider)
        assert calls == ["create", "resume"]


def test_stale_checkpoint_after_conflict_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
        lambda *_args: StitchCommandResult(returncode=EXIT_CODE_CONFLICT),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_resume",
        lambda *_args: StitchCommandResult(
            returncode=1,
            stderr="Could not find the expected commit at HEAD",
        ),
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="tried")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="resume failed"):
        run_controller(artifacts, provider)


def test_post_submit_edit_is_rejected_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    fingerprints = {"value": {"src/app.py": ("M", "content")}}
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: dict(fingerprints["value"]),
    )
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    submit_commit(artifacts)
    (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).write_text(
        "spent\n",
        encoding="utf-8",
    )
    fingerprints["value"] = {"src/app.py": ("M", "edited-after-submit")}
    with pytest.raises(
        (BuiltinCommitFinalizerError, FinalizerControllerError),
        match="stale|declaration|changed",
    ):
        run_controller(artifacts)

    runner.assert_not_called()


def test_later_finalizer_dirt_reactivates_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": ()}
    patch_dirty(monkeypatch, repo, dirty)
    mutate = ConfiguredFinalizerInstance(
        instance_id="mutate",
        provider_ref="builtin@command",
        after=("commit",),
        config={"command": ["true"], "submission": "none"},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit", "mutate"),
        required=(),
        instances={"commit": commit, "mutate": mutate},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )

    def run_mutate(*_args: object, **_kwargs: object) -> Any:
        dirty["repos"] = (dirty_repo(repo),)
        from sase.core.finalizer_wire import FinalizerInstanceResultWire

        return FinalizerInstanceResultWire(instance_id="mutate", status="success")

    monkeypatch.setattr(
        "sase.finalizers.controller.execute_non_commit_finalizer",
        run_mutate,
    )

    def recover() -> InvokeResult:
        submit_commit(artifacts)
        return InvokeResult(content="recovered", usage={"input_tokens": 1})

    provider = MagicMock()
    provider.invoke.side_effect = lambda *_args, **_kwargs: recover()

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    result = run_controller(artifacts, provider)

    assert "recovered" in result.content
    assert calls == ["main"]
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["cycles"] >= 1


def test_identical_stitch_failure_skips_retry_without_spending_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `stitch_failed` retry whose inputs are unchanged must not re-run.

    Retrying an identical repository, exclude set, and message against an
    unchanged HEAD is guaranteed to fail the same way, so the host must
    detect that before spending its second (and, here, last) mutating
    attempt -- see bead sase-ti.5.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit",),
        required=(),
        instances={"commit": commit},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    calls = {"n": 0}

    def fail_stitch(
        _repo: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        return StitchCommandResult(returncode=1, stderr="hook failed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", fail_stitch)
    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
        run_controller(artifacts)
    assert calls["n"] == 1
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "failed"
    attempts = payload["instances"][0]["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert attempts[1]["diagnostic_code"] == "stitch_retry_skipped_identical_inputs"


def test_stitch_failure_with_changed_message_still_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely different retry attempt (here: a new message) must still run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit",),
        required=(),
        instances={"commit": commit},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    calls = {"n": 0}

    def fail_stitch(
        _repo: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the declaration legitimately changing before the
            # retry (e.g. a host-driven recovery resubmission).
            submit_commit(artifacts, message="fix(final): retried message")
        return StitchCommandResult(returncode=1, stderr="hook failed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", fail_stitch)
    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
        run_controller(artifacts)
    assert calls["n"] == 2
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "failed"
    attempts = payload["instances"][0]["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2]
    assert attempts[1]["diagnostic_code"] == "stitch_failed"


def test_controller_no_progress_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)

    from sase.core.finalizer_wire import FinalizerInstanceResultWire
    from sase.finalizers.commit import BuiltinCommitExecution

    executions = {"count": 0}

    def fake_execute(*_args: object, **_kwargs: object) -> BuiltinCommitExecution:
        executions["count"] += 1
        return BuiltinCommitExecution(
            invoke_result=InvokeResult(content="done"),
            result=FinalizerInstanceResultWire(instance_id="commit", status="success"),
        )

    monkeypatch.setattr(
        "sase.finalizers.controller.execute_commit_finalizer",
        fake_execute,
    )

    submit_commit(artifacts)
    with pytest.raises(FinalizerControllerError, match="no progress"):
        run_controller(artifacts)

    assert executions["count"] == 1
