"""Store coverage for crash-safe chop launch batches."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.axe import chop_batch_store as store
from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION


def _member(agent_name: str, source_index: int) -> dict[str, Any]:
    return {
        "source_index": source_index,
        "proposal_id": f"proposal-{source_index}",
        "agent_name": agent_name,
        "clan": "toobig-68",
        "clan_generation": "gen-1",
        "launch_role": "join",
        "prompt": "Fix the finding.\n#pr",
        "workspace": "git:sase",
    }


def _manifest(batch_id: str = "batch-1") -> dict[str, Any]:
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "run": {
            "routine": "guard",
            "job": "split",
            "run_id": "20261117T120000_000001",
            "preflight_digest": "preflight-abc",
        },
        "typed_bundle": {
            "bundle_id": "bundle-7",
            "bundle_digest": "digest-7",
        },
        "clan": "toobig-68",
        "clan_generation": "gen-1",
        "members": [
            _member("toobig-68.split.a1", 0),
            _member("toobig-68.split.a2", 1),
        ],
    }


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def test_create_and_load_round_trip_reserves_run_and_bundle_context(
    isolated_home: Path,
) -> None:
    created = store.create_chop_batch("guard", "split", _manifest())
    assert created["batch_id"] == "batch-1"
    assert created["status"] == "open"
    loaded = store.load_chop_batch("guard", "split", "batch-1")
    assert loaded == created
    assert loaded["run"]["preflight_digest"] == "preflight-abc"
    assert loaded["typed_bundle"] == {
        "bundle_id": "bundle-7",
        "bundle_digest": "digest-7",
    }

    summary = store.summarize_stored_batch("guard", "split", "batch-1")
    assert summary["batch_id"] == "batch-1"
    assert summary["counts"] == {
        "total": 2,
        "pending": 2,
        "dispatching": 0,
        "launched": 0,
        "skipped": 0,
        "blocked": 0,
        "cancelled": 0,
    }


def test_create_refuses_duplicates_and_unknown_schema(
    isolated_home: Path,
) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    with pytest.raises(store.ChopBatchExistsError):
        store.create_chop_batch("guard", "split", _manifest())

    bad = _manifest(batch_id="batch-bad")
    bad["schema_version"] = CHOP_BATCH_SCHEMA_VERSION + 1
    with pytest.raises(store.ChopBatchCorruptError):
        store.create_chop_batch("guard", "split", bad)

    with pytest.raises(store.ChopBatchNotFoundError):
        store.load_chop_batch("guard", "split", "batch-missing")


def test_corrupt_payload_refuses_dispatch_but_does_not_block_listing(
    isolated_home: Path,
) -> None:
    store.create_chop_batch("guard", "split", _manifest(batch_id="good"))
    corrupt_path = store.chop_batch_path("guard", "split", "bad")
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(store.ChopBatchCorruptError):
        store.load_chop_batch("guard", "split", "bad")

    pending = store.list_pending_chop_batches("guard", "split")
    assert [item["batch_id"] for item in pending] == ["good"]

    limited = store.list_pending_chop_batches("guard", "split", limit=0)
    assert limited == []


def test_writes_are_restart_safe_with_no_temp_debris(
    isolated_home: Path,
) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    updated = store.apply_chop_batch_event(
        "guard", "split", "batch-1", "begin_dispatch", member_index=0
    )
    assert updated["members"][0]["status"] == "dispatching"

    # A fresh read sees the update and no temp file was left behind.
    assert (
        store.load_chop_batch("guard", "split", "batch-1")["members"][0]["status"]
        == "dispatching"
    )
    debris = list(store.chop_batches_dir("guard", "split").glob("*.tmp"))
    assert debris == []


def test_stale_and_live_ownership(isolated_home: Path) -> None:
    routine, job = "guard", "split"
    # Live owner (this process) keeps the batch: a second caller backs off.
    assert store.acquire_chop_batch_ownership(routine, job, "batch-1") is True
    try:
        assert store.acquire_chop_batch_ownership(routine, job, "batch-1") is False
        assert store.read_chop_batch_owner(routine, job, "batch-1") is not None
        assert store.release_chop_batch_ownership(routine, job, "batch-1")
        assert store.acquire_chop_batch_ownership(routine, job, "batch-1")
    finally:
        store.release_chop_batch_ownership(routine, job, "batch-1")

    # A stale record from a dead process may be superseded.
    dead_pid = _reaped_child_pid()
    owner_path = store.chop_batch_owner_path(routine, job, "batch-stale")
    owner_path.parent.mkdir(parents=True, exist_ok=True)
    owner_path.write_text(
        json.dumps({"batch_id": "batch-stale", "pid": dead_pid}),
        encoding="utf-8",
    )
    assert store.acquire_chop_batch_ownership(routine, job, "batch-stale")
    store.release_chop_batch_ownership(routine, job, "batch-stale")
    assert store.release_chop_batch_ownership(routine, job, "batch-stale") is False


def _reaped_child_pid() -> int:
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child exits immediately
        os._exit(0)
    _, _ = os.waitpid(pid, 0)
    return pid


def test_duplicate_acknowledgement_is_idempotent(
    isolated_home: Path,
) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    store.apply_chop_batch_event(
        "guard", "split", "batch-1", "begin_dispatch", member_index=0
    )
    first = store.apply_chop_batch_event(
        "guard", "split", "batch-1", "acknowledge_launch", member_index=0
    )
    second = store.apply_chop_batch_event(
        "guard", "split", "batch-1", "acknowledge_launch", member_index=0
    )
    assert first["members"][0]["status"] == "launched"
    assert second["members"][0]["status"] == "launched"


def test_terminal_skips_never_reopen_launched_members(
    isolated_home: Path,
) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    skipped = store.apply_chop_batch_event(
        "guard",
        "split",
        "batch-1",
        "record_skip",
        member_index=1,
        reason="wait target dismissed",
    )
    assert skipped["members"][1]["status"] == "skipped"

    store.apply_chop_batch_event(
        "guard", "split", "batch-1", "begin_dispatch", member_index=0
    )
    store.apply_chop_batch_event(
        "guard", "split", "batch-1", "acknowledge_launch", member_index=0
    )
    with pytest.raises(store.ChopBatchError):
        store.apply_chop_batch_event(
            "guard",
            "split",
            "batch-1",
            "record_skip",
            member_index=0,
            reason="too late",
        )


def test_cancellation_priority_and_reconcile_selection(
    isolated_home: Path,
) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    store.apply_chop_batch_event(
        "guard", "split", "batch-1", "begin_dispatch", member_index=0
    )
    cancelled = store.apply_chop_batch_event(
        "guard",
        "split",
        "batch-1",
        "cancel_clan_generation",
        reason="user killed clan toobig-68",
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["members"][0]["status"] == "cancelled"
    with pytest.raises(store.ChopBatchError):
        store.apply_chop_batch_event(
            "guard", "split", "batch-1", "begin_dispatch", member_index=1
        )

    # Cancellation discards remaining intent: nothing relaunches.
    resume = store.reconcile_stored_batch("guard", "split", "batch-1", [])
    assert resume["to_launch"] == []
    assert resume["blocked"] == []


def test_pause_holds_dispatch_until_resume(isolated_home: Path) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    paused = store.apply_chop_batch_event(
        "guard", "split", "batch-1", "request_pause", reason="sigterm"
    )
    assert paused["status"] == "paused"
    held = store.reconcile_stored_batch("guard", "split", "batch-1", [])
    assert held["to_launch"] == []
    assert [entry["reason"] for entry in held["blocked"]] == [
        "batch_paused",
        "batch_paused",
    ]
    resumed = store.apply_chop_batch_event("guard", "split", "batch-1", "resume")
    assert resumed["status"] == "open"


def test_concurrent_updates_do_not_lose_events(
    isolated_home: Path,
) -> None:
    members = [_member(f"member-{index}", index) for index in range(8)]
    manifest = _manifest(batch_id="batch-wide")
    manifest["members"] = members
    manifest["clan"] = None
    manifest["clan_generation"] = None
    for member in manifest["members"]:
        member.pop("clan", None)
        member.pop("clan_generation", None)
    store.create_chop_batch("guard", "split", manifest)

    errors: list[BaseException] = []

    def _dispatch(index: int) -> None:
        try:
            store.apply_chop_batch_event(
                "guard",
                "split",
                "batch-wide",
                "begin_dispatch",
                member_index=index,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_dispatch, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []

    final = store.load_chop_batch("guard", "split", "batch-wide")
    assert [item["status"] for item in final["members"]] == ["dispatching"] * 8


def test_mutation_and_ownership_locks_are_separate(
    isolated_home: Path,
) -> None:
    mutation = store.chop_batches_dir("guard", "split") / (
        store.CHOP_BATCH_MUTATION_LOCK_FILENAME
    )
    ownership = store.chop_batches_dir("guard", "split") / (
        store.CHOP_BATCH_OWNERSHIP_LOCK_FILENAME
    )
    assert mutation != ownership


def test_delete_removes_manifest_and_owner(isolated_home: Path) -> None:
    store.create_chop_batch("guard", "split", _manifest())
    assert store.acquire_chop_batch_ownership("guard", "split", "batch-1")
    assert store.delete_chop_batch("guard", "split", "batch-1") is True
    with pytest.raises(store.ChopBatchNotFoundError):
        store.load_chop_batch("guard", "split", "batch-1")
    assert store.delete_chop_batch("guard", "split", "batch-1") is False
