"""Tests for Phase 4 doctor telemetry checks."""

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


def test_telemetry_status_warns_when_enabled_endpoint_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_status_payload",
        lambda **_kwargs: {
            "enabled": True,
            "metric_count": 40,
            "pushgateway": {
                "metrics_url": "http://localhost:9091/metrics",
                "reachable": False,
            },
            "exposition": {
                "metrics_url": "http://localhost:9464/metrics",
                "reachable": True,
            },
        },
    )

    check = _check_telemetry_status()

    assert check.status == "WARN"
    assert "unreachable" in check.summary
    assert check.next_steps == ("Run `sase telemetry status`.",)


def test_telemetry_health_warns_when_source_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_status_payload",
        lambda **_kwargs: {"enabled": True},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_telemetry.build_telemetry_health_payload",
        lambda _source: {"status": "unreachable", "subsystems": []},
    )

    check = _check_telemetry_health()

    assert check.status == "WARN"
    assert "metric source" in check.summary
