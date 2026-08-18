"""Reconciliation tests for the epic_resume chop script."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_epic_resume as epic_resume

from tests._axe_chop_epic_resume_helpers import (
    FAILED_AT,
    capture_canceled,
    capture_created,
    expected_counters,
    make_failed_member,
    make_live_member,
    make_runtime,
    make_snapshot,
    make_waiting_member,
    patch_epic_resume,
)


def _state(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / epic_resume._STATE_FILENAME
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_flag_disabled_creates_no_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot], flag_enabled=False)
    created = capture_created(monkeypatch)

    result = epic_resume._run(make_runtime(tmp_path))

    assert result.reason == "flag_disabled"
    assert created == []
    assert _state(tmp_path) == {}


def test_stall_raises_exactly_one_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot])
    created = capture_created(monkeypatch)

    result = epic_resume._run(make_runtime(tmp_path))

    assert result.reason is None
    assert result.counters == expected_counters(gated=1, stalled=1, epics=1)
    assert len(created) == 1
    entry = created[0]
    assert entry["request_id"].endswith("-g1")
    assert entry["project"] == "sase"
    assert entry["epic_id"] == "sase-p4"
    assert entry["epic_title"] == "Raise an EpicResume gate"
    assert entry["clan_generation"] == "20260817110000"
    assert entry["remaining_phase_count"] == 1
    assert entry["stalled_since"] == FAILED_AT.isoformat()
    assert entry["failed_members"] == [
        {
            "agent_name": "sase-p4.1",
            "bead_id": "sase-p4.1-bead",
            "finished_at": FAILED_AT.isoformat(),
        }
    ]
    assert entry["waiting_members"] == [
        {"agent_name": "sase-p4.2", "bead_id": "sase-p4.2-bead", "finished_at": None}
    ]
    assert entry["producer"] == {"chop": "epic_resume", "project": "sase"}
    state = _state(tmp_path)
    assert state["epics"]["sase"]["sase-p4"]["request_id"] == entry["request_id"]
    assert state["epics"]["sase"]["sase-p4"]["generation"] == 1
    assert state["epics"]["sase"]["sase-p4"]["settled"] is False


def test_second_tick_with_unchanged_stall_creates_no_second_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot])
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    first = epic_resume._run(make_runtime(tmp_path))
    second = epic_resume._run(make_runtime(tmp_path))

    assert first.counters == expected_counters(gated=1, stalled=1, epics=1)
    assert second.reason == "no_stall_changes"
    assert second.counters == expected_counters(skipped=1, stalled=1, epics=1)
    assert len(created) == 1
    assert canceled == []


def test_settled_gate_never_reraises_for_the_same_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot], gate_state="pending")
    created = capture_created(monkeypatch)

    epic_resume._run(make_runtime(tmp_path))

    # The human answered (or an operator canceled) the gate: it is terminal now.
    patch_epic_resume(
        monkeypatch, tmp_path, snapshots=[snapshot], gate_state="terminal"
    )
    settled = epic_resume._run(make_runtime(tmp_path))

    assert settled.counters == expected_counters(skipped=1, stalled=1, epics=1)
    state = _state(tmp_path)
    assert state["epics"]["sase"]["sase-p4"]["settled"] is True
    assert state["epics"]["sase"]["sase-p4"]["request_id"] is None

    # A third tick -- still the same fingerprint -- must not even poll the gate.
    patch_epic_resume(
        monkeypatch,
        tmp_path,
        snapshots=[snapshot],
        gate_state="pending",  # would create/skip on a fresh gate if consulted
    )
    third = epic_resume._run(make_runtime(tmp_path))

    assert third.counters == expected_counters(skipped=1, stalled=1, epics=1)
    assert len(created) == 1


def test_new_failure_regates_after_a_settled_stall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first_snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(
        monkeypatch, tmp_path, snapshots=[first_snapshot], gate_state="terminal"
    )
    created = capture_created(monkeypatch)

    epic_resume._run(make_runtime(tmp_path))  # gates
    epic_resume._run(make_runtime(tmp_path))  # settles

    second_snapshot = make_snapshot(
        make_failed_member("sase-p4.1"),
        make_failed_member("sase-p4.2"),
    )
    patch_epic_resume(
        monkeypatch, tmp_path, snapshots=[second_snapshot], gate_state="pending"
    )
    result = epic_resume._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(gated=1, stalled=1, epics=1)
    assert len(created) == 2
    assert created[0]["request_id"].endswith("-g1")
    assert created[1]["request_id"].endswith("-g2")
    assert created[0]["request_id"] != created[1]["request_id"]


def test_resumed_epic_cancels_the_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stalled_snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[stalled_snapshot])
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    epic_resume._run(make_runtime(tmp_path))

    resumed_snapshot = make_snapshot(
        make_live_member("sase-p4.land"), generation="20260817130000"
    )
    patch_epic_resume(
        monkeypatch, tmp_path, snapshots=[stalled_snapshot, resumed_snapshot]
    )
    result = epic_resume._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(canceled=1, epics=1)
    assert canceled == [("sase", "sase-p4", "epic_resumed")]
    assert len(created) == 1
    assert _state(tmp_path)["epics"] == {}


def test_closed_epic_cancels_the_pending_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot], epic_open=True)
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    epic_resume._run(make_runtime(tmp_path))

    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot], epic_open=False)
    result = epic_resume._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(canceled=1, epics=1)
    assert canceled == [("sase", "sase-p4", "epic_closed")]
    assert len(created) == 1
    assert _state(tmp_path)["epics"] == {}


def test_in_flight_resume_defers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(
        monkeypatch,
        tmp_path,
        snapshots=[snapshot],
        in_flight_epics=frozenset({"sase-p4"}),
    )
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    result = epic_resume._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(deferred=1, stalled=1, epics=1)
    assert created == []
    assert canceled == []
    assert _state(tmp_path) == {}


def test_unreadable_project_store_leaves_other_projects_working(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sase_snapshot = make_snapshot(
        make_failed_member(), make_waiting_member(), project="sase", epic_id="sase-p4"
    )
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[sase_snapshot])
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    epic_resume._run(make_runtime(tmp_path))
    pending_state = _state(tmp_path)

    other_snapshot = make_snapshot(
        make_failed_member("other-p1.1"),
        make_waiting_member("other-p1.2"),
        project="other",
        epic_id="other-p1",
    )

    def resolve_info(beads_dir: Path, _epic_id: str) -> epic_resume._EpicInfo:
        if beads_dir.name == "sase":
            raise OSError("beads store unavailable")
        return epic_resume._EpicInfo(
            open=True, title="Other epic", remaining_phase_count=2
        )

    patch_epic_resume(
        monkeypatch,
        tmp_path,
        snapshots=[sase_snapshot, other_snapshot],
        projects=["sase", "other"],
        resolve_info=resolve_info,
    )
    runtime = make_runtime(tmp_path)
    warnings: list[str] = []
    monkeypatch.setattr(runtime.log, "warning", warnings.append)
    result = epic_resume._run(runtime)

    assert result.counters == expected_counters(gated=1, stalled=1, epics=2, projects=2)
    assert canceled == []
    assert len(created) == 2
    assert any(
        "Failed to resolve epic bead sase:sase-p4" in message for message in warnings
    )
    state = _state(tmp_path)
    assert (
        state["epics"]["sase"]["sase-p4"] == pending_state["epics"]["sase"]["sase-p4"]
    )
    assert "other-p1" in state["epics"]["other"]


def test_lane_state_is_pruned_for_vanished_epics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot = make_snapshot(make_failed_member(), make_waiting_member())
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[snapshot])
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    epic_resume._run(make_runtime(tmp_path))

    patch_epic_resume(monkeypatch, tmp_path, snapshots=[])
    result = epic_resume._run(make_runtime(tmp_path))

    assert result.counters == expected_counters(canceled=1)
    assert canceled == [("sase", "sase-p4", "epic_vanished")]
    assert len(created) == 1
    assert _state(tmp_path)["epics"] == {}


def test_dry_run_creates_and_cancels_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        epic_resume,
        "_enabled_project_stores",
        lambda _log: pytest.fail("dry run enumerated projects"),
    )
    created = capture_created(monkeypatch)
    canceled = capture_canceled(monkeypatch)

    result = epic_resume._run(make_runtime(tmp_path, dry_run=True))

    assert result.reason == "dry_run"
    assert created == []
    assert canceled == []
    assert _state(tmp_path) == {}


def test_no_stalled_epics_is_a_quiet_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_epic_resume(monkeypatch, tmp_path, snapshots=[])
    created = capture_created(monkeypatch)

    result = epic_resume._run(make_runtime(tmp_path))

    assert result.reason == "no_stall_changes"
    assert result.counters == expected_counters()
    assert created == []
