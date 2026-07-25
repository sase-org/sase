"""Runtime tests for runner-slot priority deference and marker edits."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots

from tests._runner_slot_fixtures import artifact, record


def test_deprioritized_waiter_defers_until_window_elapsed(
    tmp_path: Path,
    capsys,
) -> None:
    waiter = artifact(tmp_path, "20260725120000", 101)
    better = artifact(tmp_path, "20260725120001", 102)
    claims: list[str] = []

    def scan() -> list[AgentArtifactRecordWire]:
        return [
            record(waiter),
            record(better, meta_wait_priority=10),
        ]

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots,
            "get_runner_slot_deference_seconds_per_step",
            return_value=3,
        ),
        patch.object(
            run_agent_wait_slots,
            "get_runner_slot_deference_max_seconds",
            return_value=60,
        ),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: claims.append("claim") or "started",
        )

        assert first is None
        assert parked
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["eligible_since"]
        assert marker["wait_priority_explicit"] is True
        assert capsys.readouterr().out == "Deferring for up to 30s (priority 20)\n"

        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: claims.append("claim") or "started",
        )
        assert second is None
        assert not parked
        assert capsys.readouterr().out == ""

        marker["eligible_since"] = "2026-07-25T00:00:00+00:00"
        (waiter / "waiting.json").write_text(json.dumps(marker))
        third, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: claims.append("claim") or "started",
        )

    assert third == "started"
    assert not parked
    assert claims == ["claim"]
    assert not (waiter / "waiting.json").exists()


def test_deprioritized_waiter_uses_early_exit_without_better_agent(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260725120000", 101)
    better = artifact(tmp_path, "20260725120001", 102)
    better_present = True

    def scan() -> list[AgentArtifactRecordWire]:
        records = [record(waiter)]
        if better_present:
            records.append(record(better, meta_wait_priority=10))
        return records

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots,
            "get_runner_slot_deference_seconds_per_step",
            return_value=3,
        ),
        patch.object(
            run_agent_wait_slots,
            "get_runner_slot_deference_max_seconds",
            return_value=60,
        ),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: "started",
        )
        assert first is None
        assert parked

        better_present = False
        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: "started",
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_ineligible_poll_clears_continuous_eligibility(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260725120000", 101)
    better = artifact(tmp_path, "20260725120001", 102)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "cl_name": "cl",
                "timestamp": waiter.name,
                "wait_runners": 9,
                "wait_runners_explicit": True,
                "wait_priority": 20,
                "slot_requested_at": "2026-07-25T12:00:00+00:00",
                "eligible_since": "2026-07-25T12:00:00+00:00",
            }
        )
    )
    (better / "waiting.json").write_text(
        json.dumps(
            {
                "cl_name": "cl",
                "timestamp": better.name,
                "wait_runners": 9,
                "wait_runners_explicit": True,
                "wait_priority": 1,
                "slot_requested_at": "2026-07-25T12:00:01+00:00",
            }
        )
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(waiter), record(better)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        claimed, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: "unexpected",
        )

    assert claimed is None
    assert not parked
    marker = json.loads((waiter / "waiting.json").read_text())
    assert "eligible_since" not in marker


def test_default_and_better_priorities_claim_without_deference_config(
    tmp_path: Path,
) -> None:
    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots,
            "get_runner_slot_deference_seconds_per_step",
        ) as seconds_per_step,
        patch.object(
            run_agent_wait_slots,
            "get_runner_slot_deference_max_seconds",
        ) as max_seconds,
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ) as marker_mutation,
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        for index, priority in enumerate((10, 1)):
            waiter = artifact(tmp_path, f"2026072512000{index}", 101 + index)
            claimed, parked = run_agent_wait_slots._try_claim_runner_slot(
                artifacts_dir=str(waiter),
                cl_name="cl",
                timestamp=waiter.name,
                directive_threshold=9,
                directive_priority=priority,
                claim=lambda: "started",
            )
            assert claimed == "started"
            assert not parked
            assert not (waiter / "waiting.json").exists()

    seconds_per_step.assert_not_called()
    max_seconds.assert_not_called()
    marker_mutation.assert_not_called()


def test_parked_priority_edit_overrides_original_directive(tmp_path: Path) -> None:
    waiter = artifact(tmp_path, "20260712120001", 101)
    competitor = artifact(tmp_path, "20260712120002", 102)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "cl",
                "timestamp": waiter.name,
                "wait_runners": 9,
                "wait_runners_explicit": True,
                "wait_priority": 1,
                "slot_requested_at": "2026-07-12T12:00:01+00:00",
            }
        )
    )
    (competitor / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "cl",
                "timestamp": competitor.name,
                "wait_runners": 9,
                "wait_runners_explicit": True,
                "wait_priority": 5,
                "slot_requested_at": "2026-07-12T12:00:00+00:00",
            }
        )
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(waiter), record(competitor)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: "started",
        )

    assert result == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_marker_priority_resolution_rejects_boolean_and_invalid_values() -> None:
    assert run_agent_wait_slots._marker_priority_state(None, None) == (10, False)
    assert run_agent_wait_slots._marker_priority_state(
        {"slot_requested_at": "now"}, 3
    ) == (
        3,
        True,
    )
    assert run_agent_wait_slots._marker_priority_state(
        {"slot_requested_at": "now", "wait_priority": True},
        None,
    ) == (10, False)
    assert run_agent_wait_slots._marker_priority_state(
        {"slot_requested_at": "now", "wait_priority": -1},
        4,
    ) == (4, True)


def test_marker_priority_resolution_tracks_explicit_legacy_markers() -> None:
    legacy_default = {
        "slot_requested_at": "now",
        "wait_priority": 10,
    }
    assert run_agent_wait_slots._marker_priority_state(legacy_default, None) == (
        10,
        False,
    )
    assert run_agent_wait_slots._marker_priority_state(legacy_default, 3) == (3, True)

    legacy_non_default = {
        "slot_requested_at": "now",
        "wait_priority": 20,
    }
    assert run_agent_wait_slots._marker_priority_state(legacy_non_default, 3) == (
        20,
        True,
    )

    explicit_default = {
        "slot_requested_at": "now",
        "wait_priority": 10,
        "wait_priority_explicit": True,
    }
    assert run_agent_wait_slots._marker_priority_state(explicit_default, 3) == (
        10,
        True,
    )

    implicit_non_default = {
        "slot_requested_at": "now",
        "wait_priority": 20,
        "wait_priority_explicit": False,
    }
    assert run_agent_wait_slots._marker_priority_state(implicit_non_default, 3) == (
        3,
        True,
    )
