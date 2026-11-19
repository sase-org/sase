"""Blocked holds, notice delivery, claims, and dry-run for batch recovery.

Split from ``tests.axe.test_axe_chop_batch_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe import chop_batch_recovery as recovery
from sase.axe import chop_batch_store
from sase.axe import chop_runner_script_result_keys as claim_keys
from tests.axe._test_axe_chop_batch_recovery_shared import (
    manifest,
    recovery_isolated_home,  # noqa: F401 (registers the isolated_home fixture)
)

__all__ = [
    "test_deterministic_recovery_launch_failure_is_bounded",
    "test_disabled_batch_hold_is_notified_once",
    "test_dry_run_is_readonly",
    "test_interruption_and_resume_notices_have_separate_episode_keys",
    "test_notice_delivery_retry_reuses_one_notification_row",
    "test_once_per_claim_release_follows_batch_member_journal",
    "test_typed_once_per_claim_release_uses_outer_journal",
]


def test_disabled_batch_hold_is_notified_once(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import _chop_batch_recovery_resume as resume
    from sase.notifications.store import load_notifications

    chop_batch_store.create_chop_batch("docs", "refresh", manifest("run-disabled"))
    monkeypatch.setattr(resume, "_job_disabled", lambda _job, _routine: True)
    monkeypatch.setattr("sase.axe.maintenance.read_maintenance", lambda: None)

    first = recovery.recover_pending_chop_batches("docs", "refresh")
    second = recovery.recover_pending_chop_batches("docs", "refresh")

    assert first[0].kind == second[0].kind == "blocked"
    notices = [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "chop-batch-recovery"
    ]
    assert len(notices) == 1
    assert notices[0].tags == ["chop", "batch", "hold"]
    state = chop_batch_store.load_chop_batch_notice_state(
        "docs", "refresh", "run-disabled"
    )
    episodes = list(state["episodes"].values())
    assert len(episodes) == 1
    assert episodes[0]["events"]["hold"]["delivered"] is True


def test_notice_delivery_retry_reuses_one_notification_row(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import _chop_batch_recovery_shared as recovery_shared
    from sase.notifications.store import load_notifications

    chop_batch_store.create_chop_batch("docs", "refresh", manifest("run-notice-retry"))
    episode_id = recovery_shared.prepare_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-notice-retry",
        event="hold",
        launched=0,
        remaining=3,
        reason="maintenance",
        hold_key="maintenance",
    )
    update_notice_state = recovery_shared.update_chop_batch_notice_state

    def fail_delivery_ack(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulated crash before outbox acknowledgement")

    monkeypatch.setattr(
        recovery_shared, "update_chop_batch_notice_state", fail_delivery_ack
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        recovery_shared.deliver_pending_batch_notices(
            "docs", "refresh", "run-notice-retry"
        )

    monkeypatch.setattr(
        recovery_shared, "update_chop_batch_notice_state", update_notice_state
    )
    recovery_shared.deliver_pending_batch_notices("docs", "refresh", "run-notice-retry")
    recovery_shared.deliver_pending_batch_notices("docs", "refresh", "run-notice-retry")

    notices = [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "chop-batch-recovery"
    ]
    assert len(notices) == 1
    assert notices[0].dedup_key.endswith(episode_id)
    assert notices[0].plus_ones == []
    event = chop_batch_store.load_chop_batch_notice_state(
        "docs", "refresh", "run-notice-retry"
    )["episodes"][episode_id]["events"]["hold"]
    assert event["delivered"] is True


def test_interruption_and_resume_notices_have_separate_episode_keys(
    isolated_home: Path,
) -> None:
    from sase.axe._chop_batch_recovery_shared import emit_batch_notice
    from sase.notifications.store import load_notifications

    chop_batch_store.create_chop_batch("docs", "refresh", manifest("run-two-episodes"))
    first_episode = emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="interrupted",
        launched=0,
        remaining=3,
    )
    emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="resumed",
        launched=0,
        remaining=3,
        episode_id=first_episode,
    )
    second_episode = emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="interrupted",
        launched=1,
        remaining=2,
    )
    emit_batch_notice(
        routine="docs",
        job="refresh",
        batch_id="run-two-episodes",
        event="resumed",
        launched=1,
        remaining=2,
        episode_id=second_episode,
    )

    assert first_episode != second_episode
    notices = [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "chop-batch-recovery"
    ]
    assert len(notices) == 4
    assert len({item.dedup_key for item in notices}) == 4
    assert all(
        first_episode in item.dedup_key or second_episode in item.dedup_key
        for item in notices
    )


def test_deterministic_recovery_launch_failure_is_bounded(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-bounded-failure")
    batch["members"] = batch["members"][:1]
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())

    def fail_launch(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("deterministic launcher refusal")

    for _ in range(3):
        result = recovery.recover_pending_chop_batches(
            "docs", "refresh", launch_agents_from_cwd_fn=fail_launch
        )

    stored = chop_batch_store.load_chop_batch("docs", "refresh", "run-bounded-failure")
    assert stored["members"][0]["status"] == "blocked"
    assert "3 times" in stored["members"][0]["status_reason"]
    assert result[0].blocked[0]["status"] == "blocked"
    assert "deterministic launcher refusal" in result[0].blocked[0]["reason"]


def test_once_per_claim_release_follows_batch_member_journal(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-claims", None)
    batch["members"].append(
        {
            "source_index": 3,
            "proposal_id": "proposal-3",
            "agent_name": "job-3",
            "prompt": "%id:job-3\nDo 3.",
            "workspace": "git:sase",
        }
    )
    for index, member in enumerate(batch["members"]):
        member["dedupe_key"] = "shared-key" if index in {2, 3} else f"key-{index}"
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-claims", "begin_dispatch", member_index=0
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-claims",
        "record_skip",
        member_index=1,
        reason="explicit name collision",
    )

    released: list[str] = []
    monkeypatch.setattr(
        claim_keys,
        "release_chop_once_per_keys",
        lambda _routine, _job, keys: released.extend(keys) or len(keys),
    )
    proposals = [
        SimpleNamespace(
            index=index,
            dedupe_key="shared-key" if index in {2, 3} else f"key-{index}",
        )
        for index in range(4)
    ]

    claim_keys.release_unlaunched_once_per_keys(
        lumberjack_name="docs",
        chop_name="refresh",
        run_id="run-claims",
        accepted_proposals=proposals,
        successful_launches=[],
    )

    assert released == ["key-1"]


def test_typed_once_per_claim_release_uses_outer_journal(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = manifest("run-typed-claims", None)
    batch["members"].append(
        {
            "source_index": 3,
            "proposal_id": "proposal-3",
            "agent_name": "job-3",
            "prompt": "%id:job-3\nDo 3.",
            "workspace": "git:sase",
        }
    )
    batch["typed_bundle"] = {
        "bundle_id": "bundle-typed-claims",
        "bundle_digest": "digest-typed-claims",
    }
    for index, member in enumerate(batch["members"]):
        member["dedupe_key"] = (
            "shared-typed-key" if index in {2, 3} else f"typed-key-{index}"
        )
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-typed-claims",
        "begin_dispatch",
        member_index=0,
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-typed-claims",
        "record_skip",
        member_index=1,
        reason="condition false",
    )

    released: list[str] = []
    monkeypatch.setattr(
        claim_keys,
        "release_chop_once_per_keys",
        lambda _routine, _job, keys: released.extend(keys) or len(keys),
    )
    typed_admission = {
        "units": [
            {
                "logical_id": f"unit-{index}",
                "proposal_index": index,
                "dedupe_key": (
                    "shared-typed-key" if index in {2, 3} else f"typed-key-{index}"
                ),
            }
            for index in range(3)
        ]
    }
    result = SimpleNamespace(
        unit_results=[
            SimpleNamespace(logical_id=f"unit-{index}", outcome="launch_error")
            for index in range(4)
        ]
    )

    claim_keys.release_typed_nonlaunched_once_per_keys(
        lumberjack_name="docs",
        chop_name="refresh",
        run_id="run-typed-claims",
        typed_admission=typed_admission,
        admission_result=result,
        after="typed test",
    )

    assert released == ["typed-key-1"]


def test_dry_run_is_readonly(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe import _chop_batch_recovery_resume as resume_module

    batch = manifest("run-dry-readonly")
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    monkeypatch.setattr(resume_module, "_job_disabled", lambda _job, _routine: True)
    monkeypatch.setattr("sase.axe.maintenance.read_maintenance", lambda: None)

    def snapshot() -> dict[str, bytes]:
        root = isolated_home
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    before = snapshot()
    launched: list[Any] = []

    def fail_launcher(*args: Any, **kwargs: Any) -> Any:
        launched.append(True)
        raise AssertionError("dry-run must never invoke a launcher")

    result = recovery.recover_pending_chop_batches(
        "docs", "refresh", dry_run=True, launch_agents_from_cwd_fn=fail_launcher
    )
    after = snapshot()
    assert before == after
    assert launched == []
    assert result[0].kind == "blocked"
    # Disabled hold must not have created a notice sidecar either.
    assert (
        chop_batch_store.load_chop_batch_notice_state(
            "docs", "refresh", "run-dry-readonly"
        )
        == {}
    )
