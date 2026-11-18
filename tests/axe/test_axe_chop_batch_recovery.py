"""Recovery entry point: resume unfinished batches and honor clan kills."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe import chop_batch_recovery as recovery
from sase.axe import chop_batch_store
from sase.axe.chop_stop_signal import ChopStopSignal
from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION


def _manifest(batch_id: str = "run-1", clan: str | None = "clan-a") -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    for index in range(3):
        member: dict[str, Any] = {
            "source_index": index,
            "agent_name": f"job-{index}",
            "prompt": f"%id:job-{index}\nDo {index}.",
            "workspace": "git:sase",
        }
        if clan is not None:
            member["clan"] = clan
        members.append(member)
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "run": {"routine": "docs", "job": "refresh", "run_id": batch_id},
        "members": members,
    }


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


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
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-1"))
    assert recovery.has_unfinished_chop_batch("docs", "refresh") is True
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is not None
    chop_batch_store.apply_chop_batch_event(
        "docs", "refresh", "run-1", "cancel_clan_generation", reason="kill clan-a"
    )
    assert recovery.has_unfinished_chop_batch("docs", "refresh") is False
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is None


def test_cancel_targets_only_matching_clan_generation(
    isolated_home: Path,
) -> None:
    chop_batch_store.create_chop_batch("docs", "refresh", _manifest("run-1", "clan-a"))
    other = _manifest("run-2", "clan-b")
    chop_batch_store.create_chop_batch("docs", "refresh", other)
    cancelled = recovery.cancel_chop_batches_for_clan(
        "clan-a", reason="explicit TUI clan kill of clan-a"
    )
    assert [entry["batch_id"] for entry in cancelled] == ["run-1"]
    assert recovery.pending_batch_for_run("docs", "refresh", "run-1") is None
    assert recovery.pending_batch_for_run("docs", "refresh", "run-2") is not None


def test_cancel_never_fires_for_individual_member_selection() -> None:
    member = SimpleNamespace(
        is_clan_container=False, agent_clan="clan-a", agent_clan_generation=None
    )
    from sase.ace.tui.actions.agents._clan_cleanup import (
        cancel_pending_batches_for_clan_selection,
    )

    assert cancel_pending_batches_for_clan_selection([member]) == 0


def test_collect_observations_marks_recorded_spawn_as_matched(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest("run-9", None)
    chop_batch_store.create_chop_batch("docs", "refresh", manifest)

    record = SimpleNamespace(cl_name="job-0")
    monkeypatch.setattr(
        "sase.axe.chop_agents.get_chop_agent_records", lambda *a, **k: [record]
    )
    monkeypatch.setattr("sase.agent.names.get_active_agent_names", lambda: {"job-1"})
    observations = recovery.collect_spawn_observations("docs", "refresh", manifest)
    by_name = {item["agent_name"]: item["observation"] for item in observations}
    assert by_name["job-0"] == "matched_spawn"
    assert by_name["job-1"] == "reservation_only"
    # job-2 has no evidence and stays absent, meaning provably unspawned.
    assert "job-2" not in by_name
