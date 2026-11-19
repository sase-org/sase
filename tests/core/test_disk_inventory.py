"""Tests for the disk-inventory classifier v2 wire."""

from __future__ import annotations

from sase.core.disk_inventory import DISK_INVENTORY_WIRE_SCHEMA_VERSION
from sase.core.disk_inventory import classify_disk_inventory


def test_classify_disk_inventory_round_trips_v2_size_state() -> None:
    payload = classify_disk_inventory(
        (
            {
                "section": "workspaces",
                "name": "root",
                "path": "/tmp/root",
                "size_bytes": 0,
                "size_state": "unmeasured",
                "owner": "workspace_cleanup_and_compact",
                "horizon": "cleanup TTL 14 day(s)",
                "coverage": "complete",
            },
            {
                "section": "sase_home",
                "name": "tools",
                "path": "/tmp/tools",
                "size_bytes": 2048,
                "size_state": "lower_bound",
                "owner": "tool_run_retention",
                "horizon": "summary 180d",
            },
        )
    )

    assert payload["schema_version"] == DISK_INVENTORY_WIRE_SCHEMA_VERSION
    assert DISK_INVENTORY_WIRE_SCHEMA_VERSION == 2
    assert payload["totals_are_lower_bound"] is True
    assert payload["coverage_status"] == "partial"
    assert payload["total_bytes"] == 2048
    assert payload["unmeasured_owners"] == ["workspace_cleanup_and_compact /tmp/root"]
    assert payload["rows"][0]["coverage"] == "partial"
    assert payload["rows"][0]["size_state"] == "unmeasured"
    assert payload["rows"][1]["size_state"] == "lower_bound"
