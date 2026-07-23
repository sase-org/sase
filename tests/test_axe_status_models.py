"""Tests for the typed AXE status wire facade."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import sase.axe.status_models as models


def _request() -> models.AxeStatusRequest:
    missing = models.AxeProcessObservation(pid=None, live=None)
    return models.AxeStatusRequest(
        schema_version=models.AXE_STATUS_WIRE_SCHEMA_VERSION,
        generated_at="2026-07-23T12:00:00+00:00",
        desired_state=models.AxeDesiredStateRecord(
            state="running",
            source="test",
            timestamp="2026-07-23T11:00:00+00:00",
        ),
        orchestrator=models.AxeOrchestratorObservation(
            lifecycle_lock_held=True,
            lock_holder=models.AxeProcessObservation(pid=123, live=True),
            orchestrator_pid_file=models.AxeProcessObservation(pid=123, live=True),
            legacy_pid_file=missing,
        ),
        maintenance=None,
        hook_runners=models.AxeRunnerOccupancy(current=1, maximum=3),
        agent_runners=models.AxeRunnerOccupancy(current=2, maximum=4),
        lumberjacks=(
            models.AxeLumberjackObservation(
                name="hooks",
                configured=True,
                interval_seconds=20,
                configured_chops=("zeta", "alpha", "alpha"),
                recorded_pid=456,
                reported_state="running",
                process_live=True,
                started_at="2026-07-23T11:00:00+00:00",
                start_age_seconds=3600,
                heartbeat_at="2026-07-23T11:59:00+00:00",
                heartbeat_age_seconds=60,
                cycles_run=5,
                errors_encountered=2,
                uptime_seconds=3600,
            ),
        ),
        latest_lifecycle_event=models.AxeLifecycleEvent(
            event="start",
            timestamp="2026-07-23T11:00:00+00:00",
            source="test",
            outcome="started",
            success=True,
            reason=None,
            orchestrator_pid=123,
            age_seconds=3600,
        ),
        collection_error=None,
    )


def test_request_serialization_and_real_binding_rehydration_are_exact() -> None:
    request = _request()

    wire = models.serialize_axe_status_request(request)
    snapshot = models.classify_axe_status(request)

    assert wire["lumberjacks"][0]["configured_chops"] == [
        "zeta",
        "alpha",
        "alpha",
    ]
    assert snapshot.schema_version == models.AXE_STATUS_WIRE_SCHEMA_VERSION
    assert snapshot.state == "running"
    assert snapshot.health == "healthy"
    assert snapshot.orchestrator.live_pids == (123,)
    assert snapshot.lumberjacks[0].configured_chops == ("alpha", "zeta")
    assert snapshot.lumberjacks[0].errors_encountered == 2
    assert snapshot.to_wire()["lumberjacks"][0]["configured_chops"] == [
        "alpha",
        "zeta",
    ]
    with pytest.raises(FrozenInstanceError):
        snapshot.state = "error"  # type: ignore[misc]


def test_facade_rejects_binding_schema_mismatch(monkeypatch) -> None:
    def fake_require(name: str):
        assert name == "axe_status_wire_schema_version"
        return lambda: 2

    monkeypatch.setattr(models, "require_rust_binding", fake_require)

    with pytest.raises(models.AxeStatusWireError, match="schema mismatch"):
        models.classify_axe_status(_request())


def test_facade_rejects_malformed_binding_response(monkeypatch) -> None:
    def fake_require(name: str):
        if name == "axe_status_wire_schema_version":
            return lambda: 1
        assert name == "classify_axe_status"
        return lambda _request: {"schema_version": 1}

    monkeypatch.setattr(models, "require_rust_binding", fake_require)

    with pytest.raises(models.AxeStatusWireError, match="missing fields"):
        models.classify_axe_status(_request())


def test_rehydration_rejects_wrong_response_version() -> None:
    payload = models.classify_axe_status(_request()).to_wire()
    payload["schema_version"] = 99

    with pytest.raises(models.AxeStatusWireError, match="response schema mismatch"):
        models.rehydrate_axe_status_snapshot(payload)
