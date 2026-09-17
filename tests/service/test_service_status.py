"""Contract tests for the Rust-backed service status facade."""

from __future__ import annotations

import pytest

from sase.service.config import load_service_config
from sase.service.paths import service_status_path
from sase.service.state import (
    ServiceHostRecord,
    read_service_state,
    record_service_stop,
    set_service_enablement,
)
from sase.service.status import (
    ServiceHostObservation,
    ServiceStatusSnapshot,
    build_service_status,
    read_service_status,
    write_service_status,
)


def test_service_status_build_write_read_and_heartbeat_token_stability(
    tmp_path,
) -> None:
    config = load_service_config()
    set_service_enablement(
        "gateway",
        False,
        "pytest",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=10.0,
    )
    record_service_stop(
        "scheduler",
        "pytest",
        reason="maintenance",
        sase_home=tmp_path,
        boot_id="boot-a",
        now=11.0,
    )
    state = read_service_state(sase_home=tmp_path, boot_id="boot-a")
    host_record = ServiceHostRecord(
        pid=123,
        boot_id="boot-a",
        started_at=1.0,
        heartbeat_at=19.0,
        mode="foreground",
        sase_version="0.test",
    )

    snapshot = build_service_status(
        config,
        state,
        ServiceHostObservation(
            record=host_record,
            pid_alive=True,
            platform_unit="sase.service",
        ),
        generated_at=20.0,
        boot_id="boot-a",
    )

    assert snapshot.host.state == "running"
    scheduler = next(proc for proc in snapshot.procs if proc.name == "scheduler")
    gateway = next(proc for proc in snapshot.procs if proc.name == "gateway")
    assert scheduler.state == "stopped"
    assert scheduler.summary == "stopped until next boot"
    assert scheduler.stop is not None
    assert gateway.state == "disabled"
    assert gateway.enablement.summary == "disabled here"

    heartbeat_only = build_service_status(
        config,
        state,
        ServiceHostObservation(
            record=ServiceHostRecord(
                pid=123,
                boot_id="boot-a",
                started_at=1.0,
                heartbeat_at=20.0,
                mode="foreground",
                sase_version="0.test",
            ),
            pid_alive=True,
            platform_unit="sase.service",
        ),
        generated_at=21.0,
        boot_id="boot-a",
    )
    assert heartbeat_only.change_token == snapshot.change_token

    path = service_status_path(tmp_path)
    write_service_status(snapshot, path)
    assert read_service_status(path) == snapshot
    assert read_service_status(tmp_path / "service" / "missing.json") is None

    manual_snapshot = ServiceStatusSnapshot(
        schema_version=snapshot.schema_version,
        generated_at=snapshot.generated_at,
        change_token=snapshot.change_token,
        host=snapshot.host,
        procs=snapshot.procs,
        orphans=snapshot.orphans,
        diagnostics=snapshot.diagnostics,
    )
    manual_path = tmp_path / "service" / "manual-status.json"
    write_service_status(manual_snapshot, manual_path)
    assert read_service_status(manual_path) == snapshot


def test_service_status_validation_errors_surface_value_error(
    tmp_path,
) -> None:
    config = load_service_config()
    state = read_service_state(sase_home=tmp_path, boot_id="boot-a")

    with pytest.raises(ValueError):
        build_service_status(
            config,
            state,
            ServiceHostObservation(stale_after_seconds=0.0),
            generated_at=1.0,
            boot_id="boot-a",
        )
