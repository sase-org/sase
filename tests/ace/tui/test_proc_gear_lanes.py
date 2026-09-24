"""Tests for the proc gear lane classifier and aggregate."""

from __future__ import annotations

import re
from datetime import timedelta

from sase.ace.tui._proc_observer_models import (
    UPDATE_PROC_TYPES,
    gear_eligible_count,
    is_update_row,
    proc_gear_lane,
    proc_gear_lanes,
)
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.ace.tui.proc_producer_sites import PRODUCTION_PRODUCERS
from sase.core.time import local_now
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.procs.service_meta import SERVICE_HOST_ORIGIN

_UPDATE_RESULT_KINDS = frozenset(
    {
        "sase.update",
        "sase.update.preview",
        "agent-cli.update",
        "plugin.update",
        "plugin.mode-switch",
    }
)
_DURABLE_KINDS = frozenset(
    {"direct_submit_durable", "duck_submit_durable", "session_worker"}
)


def _row(
    proc_id: str,
    *,
    proc_type: str = "sync",
    scopes: frozenset[str] = frozenset(),
    origin: str = "",
    status: str = "running",
    age_seconds: int = 0,
    display_name: str | None = None,
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type=proc_type,
        cl_name="",
        project_file="",
        status=status,
        message=proc_id,
        started_at=local_now() - timedelta(seconds=age_seconds),
        display_name=display_name or proc_id,
        exclusive_scopes=scopes,
        origin=origin,
    )


def test_each_session_update_proc_type_is_update_lane() -> None:
    for proc_type in sorted(UPDATE_PROC_TYPES):
        row = _row(f"update-{proc_type}", proc_type=proc_type)
        assert is_update_row(row) is True
        assert proc_gear_lane(row) == "update"


def test_store_backed_plugin_update_row_is_update_lane() -> None:
    row = _row(
        "plugin-store",
        proc_type="command",
        scopes=frozenset({"plugin-update:sase-github"}),
    )
    assert is_update_row(row) is True
    assert proc_gear_lane(row) == "update"


def test_pending_plugin_update_placeholder_is_update_lane() -> None:
    row = _row("plugin-pending", proc_type="plugin.update")
    assert is_update_row(row) is True
    assert proc_gear_lane(row) == "update"


def test_install_and_plain_rows_are_proc_lane() -> None:
    for proc_type, scopes in [
        ("sync", frozenset()),
        ("plugin-install", frozenset()),
        ("agent-cli-install", frozenset()),
        ("agent-cli-plugin-install", frozenset()),
        ("plugin.install", frozenset({"plugin-install:sample"})),
        ("plugin.uninstall", frozenset({"plugin-uninstall:sample"})),
    ]:
        row = _row(f"row-{proc_type}", proc_type=proc_type, scopes=scopes)
        assert is_update_row(row) is False, proc_type
        assert proc_gear_lane(row) == "proc", proc_type


def test_monitor_row_with_update_scope_stays_monitor() -> None:
    row = _row(
        "monitor-update",
        proc_type="sase-update",
        scopes=frozenset({"sase-update"}),
        origin=MONITOR_PROC_ORIGIN,
    )
    assert proc_gear_lane(row) == "monitor"


def test_service_rows_have_no_lane() -> None:
    row = _row("service", proc_type="sase-update", origin=SERVICE_HOST_ORIGIN)
    assert proc_gear_lane(row) is None


def test_proc_gear_lanes_counts_and_oldest_first() -> None:
    old = _row("update-old", proc_type="sase-update", age_seconds=30)
    new = _row("update-new", proc_type="dev-update", age_seconds=5)
    plain = _row("plain", proc_type="sync", age_seconds=10)
    monitor = _row("mon", origin=MONITOR_PROC_ORIGIN, age_seconds=8)
    done = _row("done", proc_type="sase-update", status="success", age_seconds=50)
    dead = _row("dead", proc_type="sase-update", age_seconds=3)
    dead = ObservedProc(
        proc_id=dead.proc_id,
        proc_type=dead.proc_type,
        cl_name=dead.cl_name,
        project_file=dead.project_file,
        status=dead.status,
        message=dead.message,
        started_at=dead.started_at,
        display_name=dead.display_name,
        exclusive_scopes=dead.exclusive_scopes,
        session_id="session-dead",
        session_live=False,
    )
    projection = ProcProjection(rows=(new, plain, monitor, old, done, dead))

    lanes = proc_gear_lanes(projection)

    assert lanes.procs == 1
    assert lanes.monitors == 1
    assert lanes.updates == 2
    assert [row.proc_id for row in lanes.update_rows] == ["update-old", "update-new"]
    assert lanes.update_labels == ("update-old", "update-new")


def test_lane_totals_preserved() -> None:
    projection = ProcProjection(
        rows=(
            _row("update", proc_type="sase-update"),
            _row("plain", proc_type="sync"),
            _row("mon", origin=MONITOR_PROC_ORIGIN),
            _row("service", origin=SERVICE_HOST_ORIGIN),
            _row("done", proc_type="sync", status="success"),
        )
    )
    lanes = proc_gear_lanes(projection)
    assert lanes.procs + lanes.updates == gear_eligible_count(projection)


def _sample_scope(key: str) -> str:
    return re.sub(r"\{[^}]*\}", "sample", key)


def _synthetic_row_for_site(site: object) -> ObservedProc:
    kind = getattr(site, "kind", None)
    proc_type = str(getattr(site, "proc_type", ""))
    keys = tuple(getattr(site, "concurrency_keys", ()))
    if kind == "session_worker":
        return _row(f"site-{getattr(site, 'site_id', '')}", proc_type=proc_type)
    scopes = frozenset(_sample_scope(key) for key in keys)
    return _row(
        f"site-{getattr(site, 'site_id', '')}",
        proc_type="command",
        scopes=scopes,
    )


def test_producer_registry_guard() -> None:
    update_sites = [
        site
        for site in PRODUCTION_PRODUCERS
        if getattr(site, "result_kind", None) in _UPDATE_RESULT_KINDS
    ]
    assert update_sites, "expected update producers in the registry"
    for site in update_sites:
        row = _synthetic_row_for_site(site)
        assert proc_gear_lane(row) == "update", getattr(site, "site_id", site)
    for site in PRODUCTION_PRODUCERS:
        if getattr(site, "kind", None) not in _DURABLE_KINDS:
            continue
        if getattr(site, "result_kind", None) in _UPDATE_RESULT_KINDS:
            continue
        row = _synthetic_row_for_site(site)
        assert proc_gear_lane(row) != "update", getattr(site, "site_id", site)
