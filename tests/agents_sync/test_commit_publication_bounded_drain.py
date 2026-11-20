"""Regression coverage for bounding a stalled post-push agent-hood drain."""

from __future__ import annotations

from pathlib import Path
import signal
import time

import pytest

from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    _commit_publication_transaction_steps as transaction_steps,
    _publication_job_run as publication_job,
    git_sync,
    publication_cleanup,
    publication_timing,
)
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._commit_publication_bounded_drain_helpers import (
    configure_target,
)
from tests.agents_sync.commit_publication_fixtures import (
    BlockedStageAlarm,
    fulfilled_completion,
)
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests._sched_clock import SchedulerAdjustedClock


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


def test_blocked_render_is_bounded_and_leaves_the_request_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = configure_target(monkeypatch, tmp_path, owner)
    timings = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    alarm = BlockedStageAlarm(monkeypatch)

    def blocked_render(*_args, **_kwargs):
        alarm.expire()
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout
        raise AssertionError("blocked render should have been interrupted")

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = alarm.seconds_since_block()

    assert elapsed < 5.0
    assert outcome.queued
    assert not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].alarm_stage == "hood_publish:foo"
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
    target, _remote = configure_target(monkeypatch, tmp_path, owner)
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

    alarm = BlockedStageAlarm(monkeypatch)

    def blocked_manifest(*_args, **_kwargs):
        alarm.expire()
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish_with_scratch)
    monkeypatch.setattr(
        transaction_steps,
        "read_owner_manifest",
        blocked_manifest,
    )
    # What cleanup removes and keeps is under test here, not its one-second
    # budget (the bounded-cleanup tests below own that). A loaded runner can
    # spend that second before both path families are cleaned.
    monkeypatch.setattr(
        publication_cleanup,
        "default_publication_cleanup_timeout",
        lambda: LOAD_TOLERANT_TIMEOUT,
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


def test_after_a_blocked_render_a_later_drain_retries_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    configure_target(monkeypatch, tmp_path, owner)
    # The retry drain keeps this hang-guard budget: it must succeed, so the
    # budget only has to catch a hang.
    alarm = BlockedStageAlarm(monkeypatch)

    def blocked_render(*_args, **_kwargs):
        alarm.expire()
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)

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
    target, _remote = configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    monkeypatch.setattr(
        publication_cleanup,
        "default_publication_cleanup_timeout",
        lambda: 1.0,
    )

    sidecar = target.sidecar_path
    alarm = BlockedStageAlarm(monkeypatch)
    # Time each worktree clean without the run-queue wait: with a lock present
    # the owner probe walks every process in /proc, which a CPU-starved runner
    # stretches well past the budget though the probe itself never sleeps.
    clean_seconds: list[float] = []
    real_clean = git_sync.clean_publication_worktree

    def timed_clean(*args, **kwargs):
        clock = SchedulerAdjustedClock()
        try:
            return real_clean(*args, **kwargs)
        finally:
            clean_seconds.append(clock.elapsed())

    monkeypatch.setattr(git_sync, "clean_publication_worktree", timed_clean)

    def blocked_render_with_lock(*_args, **_kwargs):
        git_dir = sidecar / ".git"
        try:
            git_dir.mkdir(parents=True, exist_ok=True)
            (git_dir / "index.lock").write_bytes(b"test contention")
        except OSError:
            pass
        alarm.expire()
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout
        raise AssertionError("blocked render should have been interrupted")

    monkeypatch.setattr(
        publication_locked, "publish_agent_hood", blocked_render_with_lock
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = alarm.seconds_since_block()

    assert elapsed < 5.0, f"contention cleanup overran: {elapsed:.2f}s"
    assert outcome.queued
    assert not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings and timings[-1].alarm_fired
    assert timings[-1].outcome == "timeout"
    # Shared cleanup cap: post-alarm cleanup must not approach the old
    # 14s backoff+age-wait. Patch the Rust cap to 1s so lock retry cannot
    # spend the measured 15s production budget.
    assert "cleanup" in timings[-1].stage_durations
    assert len(clean_seconds) == 2  # pre-transaction clean, exception cleanup
    cleanup_seconds = clean_seconds[-1]
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
def test_inventory_slice_defers_without_charging_and_maps_to_standing_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    configure_target(monkeypatch, tmp_path, owner)
    timings = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    monkeypatch.setattr(publication_timing, "INVENTORY_BUILD_BUDGET_SECONDS", 0.2)
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="foo--code",
            global_agent="alice.athena.foo--code",
            primary_revision="a" * 40,
            local_hood="foo",
        )
    )

    def slow_inventory(*_args, **_kwargs):
        time.sleep(1.0)  # sase-test-wait: simulate inventory work exceeding its budget

    monkeypatch.setattr(
        publication_locked, "build_project_hood_inventory", slow_inventory
    )
    outcome = publication_drain.drain_agent_publications("proj")

    [remaining] = list_agent_publications("proj", include_quarantined=False)
    assert outcome.queued
    assert outcome.failure_stage == "inventory_build"
    assert outcome.error is not None and "inventory_build" in outcome.error
    assert remaining.attempts == 0
    assert timings[-1].alarm_stage == "inventory_build"
    assert (
        publication_job._standing_kind_for_result(
            publication_job.ProjectPass(error=outcome.error)
        )
        == publication_job.STANDING_KIND_DRAIN_TIMEOUT
    )
