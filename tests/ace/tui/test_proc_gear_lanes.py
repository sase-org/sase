"""Tests for the proc gear lane classifier and aggregate."""

from __future__ import annotations

import re
from datetime import timedelta

from sase.ace.tui._proc_observer_models import (
    UPDATE_PROC_TYPES,
    _is_tool_run_carrier,
    _tool_run_ids_for_row,
    is_gear_eligible_row,
    is_install_mutation_row,
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
    tags: tuple[str, ...] = (),
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
        tags=tags,
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
        assert proc_gear_lane(row) == "bg", proc_type
        if proc_type in {"plugin.install", "plugin.uninstall"}:
            assert is_install_mutation_row(row) is True, proc_type
        elif proc_type == "sync":
            assert is_install_mutation_row(row) is False


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

    assert lanes.bg == 1
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
    eligible = sum(1 for row in projection.active_rows() if is_gear_eligible_row(row))
    assert lanes.bg + lanes.updates == eligible == 2


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


def test_tool_run_carriers_are_never_bg() -> None:
    escalated = _row("tool-1", origin="tool-run")
    detached = _row("tool-2", tags=("tool-run", "tool-run:run-2"))
    catalog = _row("tool-3", tags=("tool-run:run-3",))
    command_line = _row("ace-1", proc_type="command", origin="ace")
    adopt = _row(
        "mon-adopt",
        origin=MONITOR_PROC_ORIGIN,
        tags=("tool-run", "tool-run:run-4"),
    )
    join = _row(
        "mon-join",
        origin=MONITOR_PROC_ORIGIN,
        tags=("tool-run-join:run-5",),
    )
    for row in (escalated, detached, catalog, adopt, join):
        assert _is_tool_run_carrier(row) is True, row.proc_id
        assert proc_gear_lane(row) == "tool", row.proc_id
    # The `: tool run` Command Line owner is drawn once, in the tool lane.
    assert proc_gear_lane(command_line) == "bg"
    assert (
        proc_gear_lane(command_line, tool_run_owner_proc_ids=frozenset({"ace-1"}))
        == "tool"
    )
    # A bare monitor stays orange; update and service precedence holds.
    bare = _row("mon-bare", origin=MONITOR_PROC_ORIGIN)
    assert _is_tool_run_carrier(bare) is False
    assert proc_gear_lane(bare) == "monitor"
    update_carrier = _row(
        "update-tool",
        proc_type="sase-update",
        tags=("tool-run:run-6",),
    )
    assert proc_gear_lane(update_carrier) == "update"
    service_carrier = _row(
        "service-tool",
        origin=SERVICE_HOST_ORIGIN,
        tags=("tool-run:run-7",),
    )
    assert proc_gear_lane(service_carrier) is None


def test_tool_run_ids_for_row_reads_owner_and_join_tags() -> None:
    row = _row(
        "carrier",
        origin=MONITOR_PROC_ORIGIN,
        tags=("tool-run", "tool-run:run-a", "tool-run-join:run-b"),
    )
    assert _tool_run_ids_for_row(row) == frozenset({"run-a", "run-b"})
    assert _tool_run_ids_for_row(_row("plain")) == frozenset()


def test_tool_lane_partition_counts_and_ids() -> None:
    projection = ProcProjection(
        rows=(
            _row("bg-1", proc_type="sync"),
            _row("tool-1", origin="tool-run"),
            _row(
                "mon-join",
                origin=MONITOR_PROC_ORIGIN,
                tags=("tool-run-join:run-9",),
            ),
            _row("mon-bare", origin=MONITOR_PROC_ORIGIN),
        )
    )
    lanes = proc_gear_lanes(projection)
    assert lanes.bg == 1
    assert lanes.tool_procs == 2
    assert lanes.monitors == 1
    assert lanes.tool_run_ids == frozenset({"run-9"})
    assert lanes.monitor_names == ("mon-bare",)
