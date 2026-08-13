"""Tests for monitor-reference resolution in :mod:`sase.monitor.store`."""

from __future__ import annotations

import pytest

from sase.monitor.models import MonitorRecord, MonitorRefError
from sase.monitor.store import resolve_monitor_ref


def test_resolve_monitor_ref_matches_a_unique_id_prefix() -> None:
    records = [_fake_record(monitor_id="aaabbbcccddd", lane="acme")]

    resolved = resolve_monitor_ref("aaab", records)

    assert resolved.monitor_id == "aaabbbcccddd"


def test_resolve_monitor_ref_matches_the_exact_member_agent_name() -> None:
    records = [
        _fake_record(monitor_id="aaa", lane="acme", member_agent_name="acme--mon"),
        _fake_record(monitor_id="bbb", lane="beta", member_agent_name="beta--mon"),
    ]

    resolved = resolve_monitor_ref("acme--mon", records)

    assert resolved.monitor_id == "aaa"


def test_resolve_monitor_ref_prefers_the_active_monitor_for_a_lane() -> None:
    finished = _fake_record(
        monitor_id="aaa",
        lane="acme",
        timestamp="20260812120000",
        state="completed",
        settled=True,
    )
    active = _fake_record(
        monitor_id="bbb", lane="acme", timestamp="20260812110000", state="running"
    )
    records = [finished, active]

    resolved = resolve_monitor_ref("acme", records)

    assert resolved.monitor_id == "bbb"


def test_resolve_monitor_ref_falls_back_to_the_newest_when_a_lane_has_no_active_one() -> (
    None
):
    older = _fake_record(monitor_id="aaa", lane="acme", timestamp="20260812110000")
    newer = _fake_record(monitor_id="bbb", lane="acme", timestamp="20260812120000")

    resolved = resolve_monitor_ref("acme", [older, newer])

    assert resolved.monitor_id == "bbb"


def test_resolve_monitor_ref_rejects_an_empty_reference() -> None:
    with pytest.raises(MonitorRefError):
        resolve_monitor_ref("  ", [_fake_record(monitor_id="aaa", lane="acme")])


def test_resolve_monitor_ref_rejects_a_short_unknown_id_prefix() -> None:
    with pytest.raises(MonitorRefError):
        resolve_monitor_ref("zz", [_fake_record(monitor_id="aaa", lane="acme")])


def test_resolve_monitor_ref_reports_an_ambiguous_id_prefix() -> None:
    records = [
        _fake_record(monitor_id="aaabbb111111", lane="acme"),
        _fake_record(monitor_id="aaabbb222222", lane="beta"),
    ]

    with pytest.raises(MonitorRefError):
        resolve_monitor_ref("aaabbb", records)


def _fake_record(
    *,
    monitor_id: str,
    lane: str,
    member_agent_name: str | None = None,
    timestamp: str = "20260812120000",
    state: str = "running",
    settled: bool = False,
) -> MonitorRecord:
    return MonitorRecord(
        monitor_id=monitor_id,
        member_agent_name=member_agent_name or f"{lane}--mon",
        lane=lane,
        project_name="proj",
        artifacts_dir=f"/irrelevant/{monitor_id}",
        timestamp=timestamp,
        command="sleep 60",
        cwd="/work",
        reason="test",
        label="sleep",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=60.0,
        tail_lines=200,
        monitor_state=state,  # type: ignore[arg-type]
        settled=settled,
    )
