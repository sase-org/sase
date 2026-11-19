"""Clan cancel and generation gating for chop batch recovery.

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
from sase.axe.chop_stop_signal import ChopStopSignal
from sase.axe.state import ChopRunEntry, chop_run_log_path, start_chop_run
from tests.axe._test_axe_chop_batch_recovery_shared import (
    manifest,
    record_spawn,
    recovery_isolated_home,  # noqa: F401 (registers the isolated_home fixture)
)

__all__ = [
    "test_cancel_matches_a_secondary_clan_in_the_batch",
    "test_cancel_never_fires_for_individual_member_selection",
    "test_cancel_scoped_to_requested_clan_generation",
    "test_cancel_targets_only_matching_clan_generation",
    "test_cancelled_dead_executor_no_spawn_settles",
    "test_cancelled_dead_executor_proven_spawn_acknowledges",
    "test_older_generation_does_not_cancel_a_batch_without_recorded_generation",
    "test_pending_batch_for_run_skips_complete_batches",
    "test_pending_batch_for_run_waits_for_cancelled_inflight_dispatch",
    "test_rust_generation_match_binding_rejects_older_unrecorded_generation",
    "test_rust_generation_match_binding_scopes_to_clan",
    "test_stop_signal_is_thread_safe_pause_fn",
    "test_typed_bundle_cancel_failure_is_logged_and_surfaced",
]


def test_stop_signal_is_thread_safe_pause_fn() -> None:
    signal = ChopStopSignal()
    assert signal.stop_requested() is False
    assert signal() is False
    signal.request_stop()
    assert signal.stop_requested() is True
    assert signal() is True
    assert signal.as_pause_fn()() is True


def test_pending_batch_for_run_skips_complete_batches(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", manifest("run-1"))
    assert recovery.has_unfinished_chop_batch("docs", "refresh") is True
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is not None
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-1", "cancel_clan_generation", reason="kill clan-a"
    )
    assert recovery.has_unfinished_chop_batch("docs", "refresh") is False
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is None


def test_pending_batch_for_run_waits_for_cancelled_inflight_dispatch(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", manifest("run-cancel"))
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-cancel", "begin_dispatch", member_index=0
    )

    cancelled = chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "run-cancel",
        "cancel_clan_generation",
        reason="kill during spawn",
    )

    assert cancelled["members"][0]["status"] == "dispatching"
    assert recovery.pending_batch_for_run("docs", "refresh", "run-cancel") is not None

    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-cancel", "acknowledge_launch", member_index=0
    )
    assert recovery.pending_batch_for_run("docs", "refresh", "run-cancel") is None


def test_cancel_targets_only_matching_clan_generation(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", manifest("run-1", "clan-a"))
    other = manifest("run-2", "clan-b")
    chop_batch_store.create_chop_batch("docs", "refresh", other)
    cancelled = recovery.cancel_chop_batches_for_clan(
        "clan-a", reason="explicit TUI clan kill of clan-a"
    )
    assert [entry["batch_id"] for entry in cancelled] == ["run-1"]
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is None
    assert recovery.pending_batch_for_run("docs", "refresh", "run-2") is not None


def test_cancel_matches_a_secondary_clan_in_the_batch(
    isolated_home: Path,
) -> None:
    batch = manifest("run-multi-clan", "clan-a")
    batch["members"][1]["clan"] = "clan-b"
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    cancelled = recovery.cancel_chop_batches_for_clan(
        "clan-b", reason="explicit TUI clan kill of clan-b"
    )

    assert [entry["batch_id"] for entry in cancelled] == ["run-multi-clan"]
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "run-multi-clan")["status"]
        == "cancelled"
    )


def test_older_generation_does_not_cancel_a_batch_without_recorded_generation(
    isolated_home: Path,
) -> None:
    batch = manifest("run-new-clan", None)
    batch["created_at"] = "2026-11-18T12:00:00+00:00"
    batch["members"][0]["clan"] = "reused-clan"
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    cancelled = recovery.cancel_chop_batches_for_clan(
        "reused-clan",
        generation="20261117_120000",
        reason="explicit TUI clan kill of the old generation",
    )

    assert cancelled == []
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "run-new-clan")["status"]
        == "open"
    )


def test_typed_bundle_cancel_failure_is_logged_and_surfaced(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = manifest("run-typed-cancel", "clan-a")
    start_chop_run(
        ChopRunEntry(
            run_id="run-typed-cancel",
            lumberjack_name="docs",
            chop_name="refresh",
            started_at="2026-11-18T12:00:00+00:00",
            finished_at=None,
            duration_ms=0,
            status="running",
        )
    )
    batch["typed_bundle"] = {
        "bundle_id": "typed-cancel-bundle",
        "bundle_digest": "typed-cancel-digest",
    }
    chop_batch_store.create_chop_batch("docs", "refresh", batch)

    def _fail_cancel(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("could not write cancellation marker")

    monkeypatch.setattr(
        "sase.agent.direct_typed_launch.typed_launch_bundle_dir",
        lambda _bundle_id: tmp_path,
    )
    import sase.agent.launch_admission as launch_admission

    monkeypatch.setattr(
        launch_admission,
        "cancel_typed_launch_request",
        _fail_cancel,
        raising=False,
    )

    with pytest.raises(chop_batch_store.ChopBatchError, match="persisted"):
        recovery.cancel_chop_batches_for_clan(
            "clan-a",
            reason="explicit clan kill",
            routine="docs",
            job="refresh",
        )

    cancelled = chop_batch_store.load_chop_batch("docs", "refresh", "run-typed-cancel")
    assert cancelled["status"] == "cancelled"
    log = chop_run_log_path("docs", "refresh", "run-typed-cancel")
    assert "could not write cancellation marker" in log.read_text(encoding="utf-8")


def test_cancel_never_fires_for_individual_member_selection() -> None:
    member = SimpleNamespace(
        is_clan_container=False, agent_clan="clan-a", agent_clan_generation=None
    )
    from sase.ace.tui.actions.agents._clan_cleanup import (
        cancel_pending_batches_for_clan_selection,
    )

    assert cancel_pending_batches_for_clan_selection([member]) == 0


def test_cancel_scoped_to_requested_clan_generation(
    isolated_home: Path,
) -> None:
    members: list[dict[str, Any]] = []
    for index, (name, clan, generation) in enumerate(
        [
            ("a.one", "a", "20261118_120000"),
            ("b.one", "b", "20261118_130000"),
        ]
    ):
        members.append(
            {
                "source_index": index,
                "agent_name": name,
                "clan": clan,
                "clan_generation": generation,
                "prompt": f"Do {name}.",
                "workspace": "git:sase",
            }
        )
    batch = {
        "schema_version": 1,
        "batch_id": "mixed-generation",
        "run": {"routine": "docs", "job": "refresh", "run_id": "mixed-generation"},
        "members": members,
    }
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    # Wrong generation that belongs to the other clan must not cancel.
    wrong = recovery.cancel_chop_batches_for_clan(
        "a", generation="20261118_130000", reason="kill different generation of a"
    )
    assert wrong == []
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "mixed-generation")[
            "status"
        ]
        == "open"
    )
    # Correct secondary-clan generation cancels the whole batch.
    cancelled = recovery.cancel_chop_batches_for_clan(
        "b", generation="20261118_130000", reason="kill clan b"
    )
    assert [entry["batch_id"] for entry in cancelled] == ["mixed-generation"]
    assert (
        chop_batch_store.load_chop_batch("docs", "refresh", "mixed-generation")[
            "status"
        ]
        == "cancelled"
    )


def test_rust_generation_match_binding_scopes_to_clan(
    isolated_home: Path,
) -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "chop_batch_generation_matches"):
        pytest.skip("core binding not yet built; fallback covers old pins")
    from sase.core.axe_chop_facade import (
        CHOP_BATCH_SCHEMA_VERSION,
        chop_batch_generation_matches,
    )

    members: list[dict[str, Any]] = []
    for index, (name, clan, generation) in enumerate(
        [("a.one", "a", "20261118_120000"), ("b.one", "b", "20261118_130000")]
    ):
        members.append(
            {
                "source_index": index,
                "agent_name": name,
                "clan": clan,
                "clan_generation": generation,
                "prompt": f"Do {name}.",
                "workspace": "git:sase",
            }
        )
    batch = {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": "mixed-gen-rust",
        "run": {"routine": "docs", "job": "refresh", "run_id": "mixed-gen-rust"},
        "members": members,
    }
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": batch,
                "clan": "a",
                "generation": "20261118_130000",
            }
        )
        is False
    )
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": batch,
                "clan": "a",
                "generation": "20261118_120000",
            }
        )
        is True
    )
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": batch,
                "clan": "b",
                "generation": "20261118_130000",
            }
        )
        is True
    )


def test_rust_generation_match_binding_rejects_older_unrecorded_generation(
    isolated_home: Path,
) -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "chop_batch_generation_matches"):
        pytest.skip("core binding not yet built; fallback covers old pins")
    from sase.core.axe_chop_facade import (
        CHOP_BATCH_SCHEMA_VERSION,
        chop_batch_generation_matches,
    )

    batch = {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": "unrecorded-gen-rust",
        "created_at": "2026-11-18T12:00:00+00:00",
        "run": {"routine": "docs", "job": "refresh", "run_id": "unrecorded-gen-rust"},
        "members": [
            {
                "source_index": 0,
                "agent_name": "a.one",
                "clan": "reused-clan",
                "prompt": "Do a.one.",
                "workspace": "git:sase",
            }
        ],
    }
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": batch,
                "clan": "reused-clan",
                "generation": "20261117_120000",
            }
        )
        is False
    )
    assert (
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": batch,
                "clan": "reused-clan",
                "generation": "20261118_120000",
            }
        )
        is True
    )


def test_cancelled_dead_executor_no_spawn_settles(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.names.get_blocked_local_namespace_roots", lambda: {}
    )
    monkeypatch.setattr("sase.agent.names.lookup_registered_name", lambda name: None)
    batch = manifest("cancelled-lost-ack")
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "cancelled-lost-ack", "begin_dispatch", member_index=0
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "cancelled-lost-ack",
        "cancel_clan_generation",
        reason="kill while executor dies",
    )
    assert (
        recovery.pending_batch_for_run("docs", "refresh", "cancelled-lost-ack")
        is not None
    )
    results = recovery.recover_pending_chop_batches("docs", "refresh", dry_run=False)
    assert any(
        item.batch_id == "cancelled-lost-ack" and item.kind in {"cancelled", "blocked"}
        for item in results
    )
    refreshed = chop_batch_store.load_chop_batch(
        "docs", "refresh", "cancelled-lost-ack"
    )
    # No spawn evidence: dispatching settles to cancelled without launching.
    assert refreshed["members"][0]["status"] in {"cancelled", "dispatching"}
    if refreshed["members"][0]["status"] == "cancelled":
        assert (
            recovery.pending_batch_for_run("docs", "refresh", "cancelled-lost-ack")
            is None
        )


def test_cancelled_dead_executor_proven_spawn_acknowledges(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: set())
    monkeypatch.setattr(
        "sase.agent.names.get_blocked_local_namespace_roots", lambda: {}
    )
    monkeypatch.setattr("sase.agent.names.lookup_registered_name", lambda name: None)
    batch = manifest("cancelled-proven-spawn")
    batch["members"] = batch["members"][:1]
    chop_batch_store.create_chop_batch("docs", "refresh", batch)
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "cancelled-proven-spawn", "begin_dispatch", member_index=0
    )
    record_spawn(run_id="cancelled-proven-spawn", index=0, proposal_id="proposal-0")
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "refresh",
        "cancelled-proven-spawn",
        "cancel_clan_generation",
        reason="kill during crossing launch",
    )
    results = recovery.recover_pending_chop_batches("docs", "refresh", dry_run=False)
    assert any(item.batch_id == "cancelled-proven-spawn" for item in results)
    refreshed = chop_batch_store.load_chop_batch(
        "docs", "refresh", "cancelled-proven-spawn"
    )
    assert refreshed["members"][0]["status"] == "launched"
