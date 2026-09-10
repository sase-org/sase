"""Shared capacity-scan reuse and jittered runner-slot backoff."""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.axe.run_agent_wait_slot_poll import (
    _runner_slot_poll_interval,
    _runner_slot_poll_max_interval,
    _sleep_for_runner_slot_poll,
)
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.runner_slots import (
    load_or_refresh_runner_slot_scan,
    notify_runner_slot_state_changed,
    runner_slot_state_token,
)

from tests._runner_slot_fixtures import artifact, record


def test_poll_interval_stays_near_base_on_first_attempt() -> None:
    for seed in range(20):
        value = _runner_slot_poll_interval(0, base=2.0, rng=random.Random(seed))
        assert 1.7 <= value <= 2.3


def test_poll_interval_grows_then_caps_at_ten_times_base() -> None:
    cap = _runner_slot_poll_max_interval(2.0)
    assert cap == 20.0
    first = _runner_slot_poll_interval(0, base=2.0, rng=random.Random(1))
    later = _runner_slot_poll_interval(3, base=2.0, rng=random.Random(1))
    capped = _runner_slot_poll_interval(8, base=2.0, rng=random.Random(1))
    assert first < later <= cap
    assert capped <= cap


def test_poll_max_interval_scales_with_patched_base() -> None:
    assert _runner_slot_poll_max_interval(0.01) == 0.1


def test_sleep_returns_true_when_slot_state_token_changes() -> None:
    sleeps: list[float] = []

    def token() -> str:
        return "a" if not sleeps else "b"

    changed = _sleep_for_runner_slot_poll(
        10.0,
        "a",
        probe_interval=2.0,
        killed=lambda: False,
        token=token,
        clock=lambda: float(len(sleeps)),
        sleeper=sleeps.append,
    )

    assert changed is True
    assert sleeps == [2.0]


def test_sleep_returns_false_when_timeout_elapses_unchanged() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    changed = _sleep_for_runner_slot_poll(
        5.0,
        "tok",
        probe_interval=2.0,
        killed=lambda: False,
        token=lambda: "tok",
        clock=lambda: now[0],
        sleeper=sleeper,
    )

    assert changed is False
    assert sleeps == [2.0, 2.0, 1.0]


def test_advance_resets_backoff_when_token_changed_before_sleep() -> None:
    from sase.axe.run_agent_wait_slot_poll import advance_runner_slot_poll

    attempts: list[int] = []

    def fake_interval(
        attempt: int,
        *,
        base: float,
        max_interval: float,
    ) -> float:
        del base, max_interval
        attempts.append(attempt)
        return 1.0

    with (
        patch(
            "sase.axe.run_agent_wait_slot_poll._runner_slot_poll_interval",
            fake_interval,
        ),
        patch(
            "sase.axe.run_agent_wait_slot_poll._sleep_for_runner_slot_poll",
            return_value=True,
        ),
    ):
        next_attempt, seen = advance_runner_slot_poll(
            4,
            "old",
            base=2.0,
            killed=lambda: False,
            token=lambda: "new",
        )

    assert attempts == [0]
    assert next_attempt == 0
    assert seen == "new"


def test_capacity_scan_is_reused_within_poll_window() -> None:
    calls = 0

    def collect() -> list[AgentArtifactRecordWire]:
        nonlocal calls
        calls += 1
        return []

    first = load_or_refresh_runner_slot_scan(collect, max_age=2.0, now=1000.0)
    second = load_or_refresh_runner_slot_scan(collect, max_age=2.0, now=1001.0)

    assert first == []
    assert second == []
    assert calls == 1


def test_capacity_scan_refreshes_after_poll_window() -> None:
    calls = 0

    def collect() -> list[AgentArtifactRecordWire]:
        nonlocal calls
        calls += 1
        return []

    load_or_refresh_runner_slot_scan(collect, max_age=2.0, now=1000.0)
    load_or_refresh_runner_slot_scan(collect, max_age=2.0, now=1002.0)

    assert calls == 2


def test_capacity_scan_refreshes_when_slot_state_changes() -> None:
    calls = 0

    def collect() -> list[AgentArtifactRecordWire]:
        nonlocal calls
        calls += 1
        return []

    load_or_refresh_runner_slot_scan(collect, max_age=60.0, now=1000.0)
    notify_runner_slot_state_changed()
    load_or_refresh_runner_slot_scan(collect, max_age=60.0, now=1000.5)

    assert calls == 2


def test_wait_slot_scan_uses_capacity_only_and_shares_host_cache() -> None:
    calls = 0

    def collect() -> list[AgentArtifactRecordWire]:
        nonlocal calls
        calls += 1
        return []

    with (
        patch.object(run_agent_wait_slots, "_collect_runner_slot_records", collect),
        patch.object(run_agent_wait_slots, "_RUNNER_SLOT_POLL_INTERVAL", 60),
    ):
        assert run_agent_wait_slots._RUNNER_SLOT_SCAN_OPTIONS.capacity_only is True
        run_agent_wait_slots._scan_runner_slot_records()
        run_agent_wait_slots._scan_runner_slot_records()

    assert calls == 1


def test_marker_mutation_bumps_slot_state_token(tmp_path: Path) -> None:
    before = runner_slot_state_token()
    update_agent_artifact_index_for_marker_mutation(tmp_path / "missing-artifact")
    after = runner_slot_state_token()
    assert after != before
    assert after

    delete_agent_artifact_index_artifacts([tmp_path / "missing-artifact"])
    deleted = runner_slot_state_token()
    assert deleted != after


def test_parked_retry_reuses_scan_when_waiting_marker_is_unchanged(
    tmp_path: Path,
) -> None:
    running = artifact(tmp_path, "20260712120000", 100)
    waiter = artifact(tmp_path, "20260712120001", 101)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "patch_name": "cl",
                "cl_name": "cl",
                "timestamp": waiter.name,
                "wait_runners": 0,
                "wait_runners_explicit": False,
                "wait_priority": 10,
                "wait_priority_explicit": False,
                "queue_weight": 1.0,
                "queue_weight_explicit": False,
                "slot_requested_at": "2026-07-12T12:00:01+00:00",
            }
        )
    )
    calls = 0

    def collect() -> list[AgentArtifactRecordWire]:
        nonlocal calls
        calls += 1
        return [record(running, started=True), record(waiter)]

    with (
        patch.object(run_agent_wait_slots, "_collect_runner_slot_records", collect),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.object(run_agent_wait_slots, "_RUNNER_SLOT_POLL_INTERVAL", 60),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "started",
        )
        second, parked_again = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "started",
        )

    assert first is None
    assert parked is False
    assert second is None
    assert parked_again is False
    assert calls == 1


def test_wait_for_runner_slot_resets_backoff_when_slot_state_changes(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260712120000", 101)
    outcomes: list[tuple[str | None, bool]] = [
        (None, True),
        (None, False),
        (None, False),
        ("started", False),
    ]
    sleeps: list[float] = []

    def try_claim(**_kwargs: object) -> tuple[str | None, bool]:
        return outcomes.pop(0)

    def fake_advance(
        attempt: int,
        seen_token: str,
        *,
        base: float,
        killed: object,
        token: object,
    ) -> tuple[int, str]:
        del killed, token
        sleeps.append(min(20.0, base * (2**attempt)))
        if len(sleeps) == 2:
            return 0, seen_token
        return attempt + 1, seen_token

    with (
        patch.object(
            run_agent_wait_slots, "_try_claim_runner_slot", side_effect=try_claim
        ),
        patch.object(run_agent_wait_slots, "advance_runner_slot_poll", fake_advance),
        patch.object(run_agent_wait_slots, "was_killed", return_value=False),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started = run_agent_wait_slots.wait_for_runner_slot(
            str(waiter),
            "cl",
            waiter.name,
            {"pid": 101},
            wait_runners=None,
            claim=lambda: "started",
        )

    assert started == "started"
    assert sleeps == [2.0, 4.0, 2.0]
    assert outcomes == []
