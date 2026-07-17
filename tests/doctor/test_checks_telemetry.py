"""Tests for doctor integration with the local telemetry store."""

from __future__ import annotations

from sase.doctor.checks_telemetry import (
    _check_telemetry_health,
    _check_telemetry_status,
)


def test_telemetry_status_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_status_payload",
        lambda **_kwargs: {"enabled": False, "metric_count": 12},
    )

    check = _check_telemetry_status()

    assert check.status == "SKIP"
    assert "disabled" in check.summary


def test_telemetry_status_warns_on_store_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_status_payload",
        lambda **_kwargs: {
            "enabled": True,
            "metric_count": 40,
            "store": {"sample_count": 10},
            "flusher": {"state": "error"},
            "store_error": "database busy",
        },
    )

    check = _check_telemetry_status()

    assert check.status == "WARN"
    assert "local telemetry store error" in check.details[0]
    assert check.next_steps == ("Run `sase telemetry status`.",)


def test_telemetry_status_ok_for_local_store(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_status_payload",
        lambda **_kwargs: {
            "enabled": True,
            "metric_count": 40,
            "store": {"sample_count": 10},
            "flusher": {"state": "healthy"},
            "store_error": None,
        },
    )

    check = _check_telemetry_status()

    assert check.status == "OK"
    assert "10 local sample(s)" in check.summary


def test_telemetry_health_warns_when_local_store_has_no_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_status_payload",
        lambda **_kwargs: {"enabled": True},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_health_payload",
        lambda _source: {"status": "no_data", "subsystems": []},
    )

    check = _check_telemetry_health()

    assert check.status == "WARN"
    assert "local telemetry store" in check.summary
