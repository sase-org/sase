"""Contract tests for the Rust-backed service state facade."""

from __future__ import annotations

import json

import pytest

from sase.service.paths import service_dir, service_state_path
from sase.service.state import (
    ServiceHostRecord,
    clear_service_host,
    clear_service_marker,
    clear_service_stop,
    read_service_state,
    record_service_host,
    record_service_stop,
    set_service_enablement,
    set_service_marker,
)


def test_paths_resolve_under_sase_home(tmp_path) -> None:
    assert service_dir(tmp_path) == tmp_path / "service"
    assert service_state_path(tmp_path) == tmp_path / "service" / "state.json"


def test_setting_and_clearing_enablement(tmp_path) -> None:
    outcome = set_service_enablement(
        "scheduler",
        True,
        "pytest",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=10.0,
    )

    assert outcome.changed is True
    assert service_state_path(tmp_path).exists()
    assert outcome.snapshot.state.enablement["scheduler"].enabled is True

    snapshot = read_service_state(sase_home=tmp_path, boot_id="boot-a")
    assert snapshot.state.enablement["scheduler"].updated_by == "pytest"


def test_stop_is_boot_scoped_and_expired_stop_prunes_on_next_write(
    tmp_path,
) -> None:
    record_service_stop(
        "gateway",
        "pytest",
        reason="maintenance",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=1.0,
    )

    current = read_service_state(sase_home=tmp_path, boot_id="boot-a")
    assert "gateway" in current.state.stops
    other_boot = read_service_state(sase_home=tmp_path, boot_id="boot-b")
    assert other_boot.expired_stops == ("gateway",)
    assert other_boot.state.stops == {}

    outcome = set_service_enablement(
        "scheduler",
        False,
        "pytest",
        sase_home=tmp_path,
        boot_id="boot-b",
        now=2.0,
    )
    assert outcome.snapshot.expired_stops == ("gateway",)
    assert "gateway" not in service_state_path(tmp_path).read_text(encoding="utf-8")


def test_explicit_none_boot_id_matches_only_none(tmp_path) -> None:
    record_service_stop(
        "scheduler",
        "pytest",
        sase_home=tmp_path,
        boot_id=None,
        now=1.0,
    )

    assert (
        "scheduler" in read_service_state(sase_home=tmp_path, boot_id=None).state.stops
    )
    assert read_service_state(sase_home=tmp_path, boot_id="boot-a").state.stops == {}


def test_markers_and_host_pid_guard(tmp_path) -> None:
    marker = set_service_marker(
        "handover.ready",
        "pytest",
        detail="ok",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=1.0,
    )
    assert marker.snapshot.state.markers["handover.ready"].detail == "ok"

    host = ServiceHostRecord(
        pid=123,
        boot_id="boot-a",
        started_at=1.0,
        heartbeat_at=2.0,
        mode="foreground",
        sase_version="0.test",
    )
    recorded = record_service_host(
        host,
        sase_home=tmp_path,
        boot_id="boot-a",
        now=2.0,
    )
    assert recorded.snapshot.state.host == host

    unchanged = clear_service_host(
        999,
        sase_home=tmp_path,
        boot_id="boot-a",
        now=3.0,
    )
    assert unchanged.changed is False
    assert unchanged.snapshot.state.host == host

    cleared = clear_service_host(
        123,
        sase_home=tmp_path,
        boot_id="boot-a",
        now=4.0,
    )
    assert cleared.changed is True
    assert cleared.snapshot.state.host is None

    marker_cleared = clear_service_marker(
        "handover.ready",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=5.0,
    )
    assert marker_cleared.snapshot.state.markers == {}


def test_corrupt_and_newer_schema_behavior(tmp_path) -> None:
    path = service_state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    snapshot = read_service_state(sase_home=tmp_path, boot_id="boot-a")
    assert "corrupt service state" in snapshot.diagnostics[0]
    assert path.exists()

    outcome = set_service_enablement(
        "scheduler",
        True,
        "pytest",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=12.345,
    )
    assert "quarantined" in outcome.snapshot.diagnostics[0]
    assert (path.parent / "state.json.corrupt-12345").exists()

    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "enablement": {},
                "stops": {},
                "markers": {},
                "host": None,
            }
        ),
        encoding="utf-8",
    )
    snapshot = read_service_state(sase_home=tmp_path, boot_id="boot-a")
    assert snapshot.read_only is True

    with pytest.raises(RuntimeError):
        set_service_enablement(
            "scheduler",
            True,
            "pytest",
            sase_home=tmp_path,
            boot_id="boot-a",
            now=20.0,
        )


def test_validation_errors_surface_value_error(tmp_path) -> None:
    with pytest.raises(ValueError):
        set_service_enablement(
            "Bad",
            True,
            "pytest",
            sase_home=tmp_path,
            boot_id="boot-a",
            now=1.0,
        )

    with pytest.raises(ValueError):
        record_service_stop(
            "scheduler",
            "",
            sase_home=tmp_path,
            boot_id="boot-a",
            now=1.0,
        )

    with pytest.raises(ValueError):
        clear_service_stop(
            "Bad",
            sase_home=tmp_path,
            boot_id="boot-a",
            now=1.0,
        )
