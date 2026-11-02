"""Regression coverage for bounding a stalled post-push agent-hood drain."""

from __future__ import annotations

from pathlib import Path
import signal
import time

import pytest

from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    _commit_publication_support as publication_support,
    git_sync,
)
from sase.agents_sync import (
    _commit_publication_transaction_steps as transaction_steps,
    git_sync_transaction,
)
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.agents_sync.models import TargetSelection
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import (
    fulfilled_completion,
    setup_target,
)


def _publish_readme(owner: AgentOwnerIdentity):
    def publish(_target, repo, _agent, **_kwargs):
        (repo / "README.md").write_text("# Published hood\n")
        (repo / "schema.json").write_text("{}\n")
        (repo / "families").mkdir(exist_ok=True)
        (repo / "families" / ".gitkeep").write_text("")
        (repo / "sessions").mkdir(exist_ok=True)
        (repo / "sessions" / ".gitkeep").write_text("")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (("foo", V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    return publish


def _configure_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    owner: AgentOwnerIdentity,
):
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support,
        "require_agent_owner_identity",
        lambda: owner,
    )
    return target, remote


def test_blocked_render_is_bounded_and_leaves_the_request_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    timings = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)

    def blocked_render(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout
        raise AssertionError("blocked render should have been interrupted")

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 1.0,
    )

    started = time.perf_counter()
    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert outcome.queued
    assert not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].outcome == "timeout"

    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].attempts == 1

    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, run_git) / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(lock_path, 1.0) as acquired:
        assert acquired, "stalled drain must release sase-agents-sync.lock"


def test_manifest_timeout_cleans_regenerable_paths_and_preserves_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    timings = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)

    def publish_with_scratch(_target, repo, agent, **kwargs):
        (repo / "prompts").mkdir(exist_ok=True)
        (repo / "prompts" / "scratch.md").write_text("regenerable prompt\n")
        (repo / "artifacts").mkdir(exist_ok=True)
        (repo / "artifacts" / "scratch.bin").write_bytes(b"regenerable")
        object_path = repo / "files" / "objects" / "sha256" / "aa" / "pending"
        object_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.write_bytes(b"append-only object")
        return _publish_readme(owner)(_target, repo, agent, **kwargs)

    def blocked_manifest(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish_with_scratch)
    monkeypatch.setattr(
        transaction_steps,
        "read_owner_manifest",
        blocked_manifest,
    )
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 5.0,
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert outcome.queued and not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].alarm_stage == "manifest_verify"
    assert not (target.sidecar_path / "prompts" / "scratch.md").exists()
    assert not (target.sidecar_path / "artifacts" / "scratch.bin").exists()
    assert (
        target.sidecar_path / "files" / "objects" / "sha256" / "aa" / "pending"
    ).read_bytes() == b"append-only object"
    assert not (target.sidecar_path / "README.md").exists()


def test_publication_cleanup_attempts_both_path_families_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fail_agents(*_args, **_kwargs):
        calls.append("agents")
        return "agents cleanup failed"

    def fail_archive(*_args, **_kwargs):
        calls.append("archive")
        return "archive cleanup failed"

    monkeypatch.setattr(
        git_sync_transaction, "clean_agents_payload_worktree", fail_agents
    )
    monkeypatch.setattr(
        git_sync_transaction, "clean_prompt_archive_worktree", fail_archive
    )

    error = git_sync.clean_publication_worktree(tmp_path, run_git)

    assert calls == ["agents", "archive"]
    assert error == "agents cleanup failed; archive cleanup failed"


def test_cleanup_failure_is_attached_without_replacing_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    _configure_target(monkeypatch, tmp_path, owner)
    cleanup_calls = 0

    def cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        return None if cleanup_calls == 1 else "archive cleanup failed"

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError("original publication failure")

    monkeypatch.setattr(git_sync, "clean_publication_worktree", cleanup)
    monkeypatch.setattr(publication_locked, "publish_queued_transaction", fail_publish)

    with pytest.raises(RuntimeError, match="original publication failure") as caught:
        publish_committed_agent_hood(
            "foo--code",
            "a" * 40,
            project="Project",
            git_runner=run_git,
        )

    assert cleanup_calls == 2
    assert "archive cleanup failed" in "\n".join(caught.value.__notes__)


def test_after_a_blocked_render_a_later_drain_retries_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    _configure_target(monkeypatch, tmp_path, owner)

    def blocked_render(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 1.0,
    )

    first = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert first.queued and not first.published
    assert len(list_agent_publications("proj")) == 1

    monkeypatch.setattr(
        publication_locked, "publish_agent_hood", _publish_readme(owner)
    )
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 5.0,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_completion",
        fulfilled_completion,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        lambda *_args, **_kwargs: {},
    )

    second = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert second.published and not second.error
    assert list_agent_publications("proj") == ()


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires interval timers")
def test_bounded_drain_restores_an_existing_alarm_timer() -> None:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    try:
        signal.setitimer(signal.ITIMER_REAL, 5.0, 10.0)
        with publication_drain._bounded_publication_drain(1.0):
            pass
        delay, interval = signal.getitimer(signal.ITIMER_REAL)
        assert 4.0 < delay <= 5.0
        assert interval == 10.0
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def test_blocked_render_with_young_index_lock_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Young owner-free index.lock during a blocked render stays under 5s.

    Fault-injects the post-alarm cleanup contention from the sase-xo probe:
    the blocked renderer creates a fresh sidecar ``.git/index.lock`` just
    before sleeping, so exception cleanup must recover through git-lock
    budgets instead of waiting out the 15s stale age.
    """
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)

    sidecar = target.sidecar_path

    def blocked_render_with_lock(*_args, **_kwargs):
        git_dir = sidecar / ".git"
        try:
            git_dir.mkdir(parents=True, exist_ok=True)
            (git_dir / "index.lock").write_bytes(b"test contention")
        except OSError:
            pass
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout
        raise AssertionError("blocked render should have been interrupted")

    monkeypatch.setattr(
        publication_locked, "publish_agent_hood", blocked_render_with_lock
    )
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 1.0,
    )

    started = time.perf_counter()
    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"contention cleanup overran: {elapsed:.2f}s"
    assert outcome.queued
    assert not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].outcome == "timeout"
    # Shared 1s cleanup cap: post-alarm cleanup must not approach the old
    # 14s backoff+age-wait.
    cleanup_seconds = timings[-1].stage_durations.get("cleanup", 0.0)
    assert cleanup_seconds < 2.0, f"cleanup took {cleanup_seconds:.2f}s"

    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].attempts == 1

    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, run_git) / "sase-agents-sync.lock"
    )
    with git_sync.bounded_agents_lock(lock_path, 1.0) as acquired:
        assert acquired, "stalled drain must release sase-agents-sync.lock"

    # A later drain still cleans/retries successfully after test contention
    # is removed.
    try:
        (sidecar / ".git" / "index.lock").unlink(missing_ok=True)
    except OSError:
        pass
    monkeypatch.setattr(
        publication_locked, "publish_agent_hood", _publish_readme(owner)
    )
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 5.0,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_completion",
        fulfilled_completion,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        lambda *_args, **_kwargs: {},
    )
    second = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert second.published and not second.error
    assert list_agent_publications("proj") == ()


def test_stalled_cleanup_does_not_replace_render_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 5s stall in one cleanup family stays bounded and keeps timeout attribution."""
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = _configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)

    def blocked_render(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    calls = {"count": 0}

    def stalled_agents_cleanup(repo, git_runner, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # Initial payload_clean before the transaction must succeed
            # quickly so the timeout fires in hood_publish, not here.
            return None
        time.sleep(5)  # sase-test-wait: stalled cleanup must be bounded
        return "agents cleanup stalled"

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        git_sync_transaction,
        "clean_agents_payload_worktree",
        stalled_agents_cleanup,
    )
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 1.0,
    )

    started = time.perf_counter()
    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"stalled cleanup overran: {elapsed:.2f}s"
    assert outcome.queued and not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].outcome == "timeout"
    cleanup_seconds = timings[-1].stage_durations.get("cleanup", 0.0)
    assert cleanup_seconds < 2.0, f"cleanup took {cleanup_seconds:.2f}s"

    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].attempts == 1


def test_cleanup_budget_caps_cumulative_ops(tmp_path: Path) -> None:
    """Expired budgets refuse git and cumulative cleanup cannot overrun.

    Retry/age-wait budget enforcement lives in Rust
    (``git_lock::tests::{expired_budgets_stop_before_retry_or_removal,shorter_than_next_backoff_stops_without_granting_delay,aged_lock_with_exhausted_caller_deadline_never_removes}``);
    this executor test proves the Python side never resets the shared
    deadline across families.
    """
    import subprocess
    from pathlib import Path as _Path

    from sase.agents_sync import git_sync_transaction
    from sase.agents_sync.publication_cleanup import (
        PublicationCleanupBudget,
        bounded_git_runner,
        default_publication_cleanup_timeout,
    )

    assert default_publication_cleanup_timeout() == 1.0

    # Expired budget refuses git without running it.
    expired = PublicationCleanupBudget(
        timeout_seconds=1.0, deadline=time.monotonic() - 0.1
    )
    assert expired.exhausted()
    calls: list = []

    def fake_base(cwd, args, *, network=False, op="agents_sync.git"):
        calls.append((cwd, args))
        return subprocess.CompletedProcess(args, 0, "", "")

    bounded = bounded_git_runner(fake_base, expired)
    result = bounded(_Path("/tmp"), ["status"])
    assert result.returncode == 128
    assert "budget exhausted" in (result.stderr or "")
    assert calls == []

    # Cumulative cleanup families share one deadline: an exhausted budget
    # reports unfinished cleanup without running git.
    monkey_budget = PublicationCleanupBudget(
        timeout_seconds=1.0, deadline=time.monotonic() - 0.1
    )
    calls.clear()
    error = git_sync_transaction.clean_publication_worktree(
        tmp_path,
        fake_base,
        remaining_timeout=monkey_budget.remaining_timeout,
    )
    assert error is not None and "budget exhausted" in error
    assert calls == []
