"""Cleanup coverage for bounded post-push agent-hood drains."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    git_sync,
    git_sync_transaction,
    publication_cleanup,
)
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._commit_publication_bounded_drain_helpers import (
    configure_target,
)
from tests.agents_sync.commit_publication_fixtures import BlockedStageAlarm


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
    configure_target(monkeypatch, tmp_path, owner)
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


def test_stalled_cleanup_does_not_replace_render_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 5s stall in one cleanup family stays bounded and keeps timeout attribution."""
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    monkeypatch.setattr(
        publication_cleanup,
        "default_publication_cleanup_timeout",
        lambda: 1.0,
    )
    alarm = BlockedStageAlarm(monkeypatch)

    def blocked_render(*_args, **_kwargs):
        alarm.expire()
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    calls = {"count": 0}

    def stalled_agents_cleanup(repo, git_runner, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return None  # the pre-transaction payload clean
        time.sleep(5)  # sase-test-wait: stalled cleanup must be bounded
        return "agents cleanup stalled"

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        git_sync_transaction,
        "clean_agents_payload_worktree",
        stalled_agents_cleanup,
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    elapsed = alarm.seconds_since_block()

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


def test_empty_drain_sweeps_stranded_publication_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    stage = target.sidecar_path / ".sase-v2-stage-deadbeef"
    backup = target.sidecar_path / ".sase-v2-backup-deadbeef"
    stage.mkdir()
    (stage / "README.md").write_text("staged\n")
    backup.mkdir()
    (backup / "README.md").write_text("backup\n")

    outcome = publication_drain.drain_agent_publications("proj")

    assert not outcome.error
    assert not stage.exists()
    assert not backup.exists()
    assert timings
    assert timings[-1].cleanup_result == "completed"
    assert timings[-1].deferred_cleanup_completed is True


def test_ledger_records_deferred_and_failed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    target, _remote = configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    alarm = BlockedStageAlarm(monkeypatch)

    def blocked_render(*_args, **_kwargs):
        alarm.expire()
        time.sleep(30)  # sase-test-wait: exceeds the drain timeout

    calls = {"count": 0}

    def deferred_cleanup(_repo: Path, _runner: object, **_kwargs: object):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return "publication cleanup budget exhausted"

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        git_sync_transaction,
        "clean_agents_payload_worktree",
        deferred_cleanup,
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert outcome.queued and not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert "publication cleanup also failed" not in outcome.error
    assert timings[-1].cleanup_result == "deferred"

    calls["count"] = 0

    def failed_cleanup(_repo: Path, _runner: object, **_kwargs: object):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return "could not restore tracked agents sidecar payload"

    monkeypatch.setattr(
        git_sync_transaction,
        "clean_agents_payload_worktree",
        failed_cleanup,
    )
    failed = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert failed.error is not None and "did not complete within" in failed.error
    assert "could not restore" not in (failed.error or "")
    assert timings[-1].cleanup_result == "failed"
