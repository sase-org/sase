"""Panel partition index over the Services-tab sidebar item list."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.axe_display._panels import (
    SERVICES_PANEL_ORDER,
    build_services_panel_index,
    services_panel_key_for_item,
)
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    ChopItem,
    LumberjackItem,
    ServiceProcItem,
)


def _items() -> list:
    return [
        ServiceProcItem(name="scheduler"),
        ServiceProcItem(name="telegram"),
        BgCmdItem(slot=1),
        BgCmdItem(slot=2),
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="refresh"),
        LumberjackItem(name="mentors"),
    ]


def test_panel_order_is_service_procs_then_routines() -> None:
    assert SERVICES_PANEL_ORDER == ("service_procs", "scheduled_routines")


def test_item_panel_membership() -> None:
    assert services_panel_key_for_item(ServiceProcItem(name="x")) == "service_procs"
    assert services_panel_key_for_item(BgCmdItem(slot=1)) == "service_procs"
    assert services_panel_key_for_item(LumberjackItem(name="x")) == "scheduled_routines"
    assert (
        services_panel_key_for_item(ChopItem(lumberjack_name="x", chop_name="y"))
        == "scheduled_routines"
    )


def test_unknown_item_type_fails_loudly() -> None:
    with pytest.raises(TypeError):
        services_panel_key_for_item(object())


def test_partition_and_global_local_mapping() -> None:
    index = build_services_panel_index(_items())
    procs = index.slice_for("service_procs")
    routines = index.slice_for("scheduled_routines")
    assert procs.global_indices == [0, 1, 2, 3]
    assert routines.global_indices == [4, 5, 6]
    assert [type(i).__name__ for i in procs.items] == [
        "ServiceProcItem",
        "ServiceProcItem",
        "BgCmdItem",
        "BgCmdItem",
    ]
    # Round-trip every global index through its panel.
    for global_idx in range(7):
        key = index.panel_for_global(global_idx)
        local = index.local_idx_for(key, global_idx)
        assert local >= 0
        assert index.slice_for(key).global_indices[local] == global_idx
    # Cross-panel lookups miss with the -1 sentinel.
    assert index.local_idx_for("service_procs", 5) == -1
    assert index.local_idx_for("scheduled_routines", 0) == -1


def test_panel_for_global_matches_visual_order() -> None:
    index = build_services_panel_index(_items())
    assert [index.panel_for_global(i) for i in range(4)] == ["service_procs"] * 4
    assert [index.panel_for_global(i) for i in range(4, 7)] == [
        "scheduled_routines"
    ] * 3


def test_empty_list_defaults_to_service_procs() -> None:
    index = build_services_panel_index([])
    assert index.panel_for_global(0) == "service_procs"
    assert index.local_idx_for("service_procs", 0) == -1
    assert index.local_idx_for("scheduled_routines", 0) == -1
    assert index.slice_for("service_procs").items == []
    assert index.slice_for("scheduled_routines").items == []


def test_out_of_range_global_defaults_to_service_procs() -> None:
    index = build_services_panel_index(_items())
    assert index.panel_for_global(99) == "service_procs"
