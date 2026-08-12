"""Tests for the typed chop-overrun wire facade."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

import sase.axe.chop_overrun as models
from sase.axe.state import ChopRunEntry
from tests._rust_extension_module_helpers import install_fake_rust_extension


def _run_entry() -> ChopRunEntry:
    return ChopRunEntry(
        run_id="20260812T100000_000000",
        lumberjack_name="hooks",
        chop_name="slow",
        started_at="2026-08-12T10:00:00+00:00",
        finished_at="2026-08-12T10:01:01+00:00",
        duration_ms=61000,
        status="success",
        script_duration_ms=61000,
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": models.CHOP_OVERRUN_WIRE_SCHEMA_VERSION,
        "level": "over",
        "sampled_runs": 1,
        "over_runs": 1,
        "worst_ratio": 1.0166666666666666,
        "worst_blocking_ms": 61000,
        "latest_ratio": 1.0166666666666666,
    }
    payload.update(overrides)
    return payload


def test_facade_returns_none_without_interval_or_runs() -> None:
    run = _run_entry()

    assert (
        models.classify_chop_overrun(
            now=datetime(2026, 8, 12, 10, 2, tzinfo=UTC),
            interval_seconds=0,
            runs=[run],
        )
        is None
    )
    assert (
        models.classify_chop_overrun(
            now=datetime(2026, 8, 12, 10, 2, tzinfo=UTC),
            interval_seconds=60,
            runs=[],
        )
        is None
    )


def test_facade_serializes_request_and_rehydrates_response(monkeypatch) -> None:
    seen: list[dict[str, Any]] = []

    def classify(request: dict[str, Any]) -> dict[str, Any]:
        seen.append(request)
        return _payload()

    install_fake_rust_extension(
        monkeypatch,
        chop_overrun_wire_schema_version=lambda: 1,
        classify_chop_overrun=classify,
    )

    verdict = models.classify_chop_overrun(
        now=datetime(2026, 8, 12, 10, 2, tzinfo=UTC),
        interval_seconds=60,
        runs=[_run_entry()],
    )

    assert verdict is not None
    assert verdict == models.ChopOverrun(
        level="over",
        sampled_runs=1,
        over_runs=1,
        worst_ratio=1.0166666666666666,
        worst_blocking_ms=61000,
        latest_ratio=1.0166666666666666,
    )
    assert seen == [
        {
            "schema_version": 1,
            "now": "2026-08-12T10:02:00+00:00",
            "interval_seconds": 60,
            "runs": [
                {
                    "status": "success",
                    "started_at": "2026-08-12T10:00:00+00:00",
                    "duration_ms": 61000,
                    "script_duration_ms": 61000,
                }
            ],
        }
    ]
    with pytest.raises(FrozenInstanceError):
        verdict.level = "none"  # type: ignore[misc]


def test_facade_rejects_binding_schema_mismatch(monkeypatch) -> None:
    install_fake_rust_extension(
        monkeypatch,
        chop_overrun_wire_schema_version=lambda: 2,
    )

    with pytest.raises(models.ChopOverrunWireError, match="schema mismatch"):
        models.classify_chop_overrun(
            now=datetime(2026, 8, 12, 10, 2, tzinfo=UTC),
            interval_seconds=60,
            runs=[_run_entry()],
        )


def test_facade_rejects_malformed_binding_response(monkeypatch) -> None:
    install_fake_rust_extension(
        monkeypatch,
        chop_overrun_wire_schema_version=lambda: 1,
        classify_chop_overrun=lambda _request: _payload(level="urgent"),
    )

    with pytest.raises(models.ChopOverrunWireError, match="unsupported level"):
        models.classify_chop_overrun(
            now=datetime(2026, 8, 12, 10, 2, tzinfo=UTC),
            interval_seconds=60,
            runs=[_run_entry()],
        )
