"""Panel partition index over the Services-tab sidebar item list."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.axe_display._panels import (
    ROUTINE_PANEL_ORDER,
    SERVICES_PANEL_ORDER,
    build_services_panel_index,
    routine_panel_key_for_source,
    _services_panel_key_for_item,
)
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    ChopItem,
    LumberjackItem,
    ServiceProcItem,
)


def _origins(**sources: str) -> dict:
    return {name: SimpleNamespace(source=source) for name, source in sources.items()}


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


def _default_origins() -> dict:
    return _origins(hooks="user", mentors="builtin")


def test_panel_order_is_service_procs_then_source_routines() -> None:
    assert SERVICES_PANEL_ORDER == (
        "service_procs",
        "user_routines",
        "plugin_routines",
        "builtin_routines",
    )
    assert ROUTINE_PANEL_ORDER == (
        "user_routines",
        "plugin_routines",
        "builtin_routines",
    )


def test_item_panel_membership() -> None:
    assert _services_panel_key_for_item(ServiceProcItem(name="x")) == "service_procs"
    assert _services_panel_key_for_item(BgCmdItem(slot=1)) == "service_procs"
    origins = _origins(x="user", p="plugin", b="builtin")
    assert (
        _services_panel_key_for_item(LumberjackItem(name="x"), origins)
        == "user_routines"
    )
    assert (
        _services_panel_key_for_item(LumberjackItem(name="p"), origins)
        == "plugin_routines"
    )
    assert (
        _services_panel_key_for_item(LumberjackItem(name="b"), origins)
        == "builtin_routines"
    )
    assert (
        _services_panel_key_for_item(
            ChopItem(lumberjack_name="p", chop_name="y"), origins
        )
        == "plugin_routines"
    )


def test_chop_uses_parent_routine_origin() -> None:
    # A job renders in its parent routine's panel even when the job's own
    # origin would differ; only the parent lookup decides membership.
    origins = _origins(hooks="builtin")
    assert (
        _services_panel_key_for_item(
            ChopItem(lumberjack_name="hooks", chop_name="fast"), origins
        )
        == "builtin_routines"
    )


def test_missing_origin_falls_back_to_user() -> None:
    assert (
        _services_panel_key_for_item(LumberjackItem(name="hooks"), {})
        == "user_routines"
    )
    assert _services_panel_key_for_item(LumberjackItem(name="hooks")) == "user_routines"


def test_unknown_source_fails_loudly() -> None:
    with pytest.raises(ValueError):
        routine_panel_key_for_source("alien")
    with pytest.raises(ValueError):
        _services_panel_key_for_item(LumberjackItem(name="x"), _origins(x="alien"))


def test_unknown_item_type_fails_loudly() -> None:
    with pytest.raises(TypeError):
        _services_panel_key_for_item(object())


def test_partition_and_global_local_mapping() -> None:
    index = build_services_panel_index(_items(), _default_origins())
    procs = index.slice_for("service_procs")
    user = index.slice_for("user_routines")
    builtin = index.slice_for("builtin_routines")
    assert procs.global_indices == [0, 1, 2, 3]
    assert user.global_indices == [4, 5]
    assert builtin.global_indices == [6]
    assert index.slice_for("plugin_routines").global_indices == []
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
    assert index.local_idx_for("user_routines", 0) == -1
    assert index.local_idx_for("builtin_routines", 0) == -1


def test_panel_for_global_matches_visual_order() -> None:
    index = build_services_panel_index(_items(), _default_origins())
    assert [index.panel_for_global(i) for i in range(4)] == ["service_procs"] * 4
    assert [index.panel_for_global(i) for i in range(4, 6)] == ["user_routines"] * 2
    assert index.panel_for_global(6) == "builtin_routines"


def test_empty_list_defaults_to_service_procs() -> None:
    index = build_services_panel_index([])
    assert index.panel_for_global(0) == "service_procs"
    assert index.local_idx_for("service_procs", 0) == -1
    assert index.local_idx_for("user_routines", 0) == -1
    assert index.slice_for("service_procs").items == []
    assert index.slice_for("user_routines").items == []


def test_out_of_range_global_defaults_to_service_procs() -> None:
    index = build_services_panel_index(_items(), _default_origins())
    assert index.panel_for_global(99) == "service_procs"


def test_first_and_last_global_per_panel() -> None:
    index = build_services_panel_index(_items(), _default_origins())
    assert index.first_global("service_procs") == 0
    assert index.last_global("service_procs") == 3
    assert index.first_global("user_routines") == 4
    assert index.last_global("user_routines") == 5
    assert index.first_global("builtin_routines") == 6
    assert index.last_global("builtin_routines") == 6


def test_first_and_last_global_empty_panel_is_none() -> None:
    index = build_services_panel_index([])
    assert index.first_global("service_procs") is None
    assert index.last_global("service_procs") is None
    assert index.first_global("user_routines") is None
    assert index.last_global("user_routines") is None
    assert index.first_global("builtin_routines") is None
    assert index.last_global("builtin_routines") is None


def test_adjacent_nonempty_panel_wraps_both_directions() -> None:
    index = build_services_panel_index(_items(), _default_origins())
    assert (
        index.adjacent_nonempty_panel("service_procs", forward=True) == "user_routines"
    )
    assert (
        index.adjacent_nonempty_panel("user_routines", forward=True)
        == "builtin_routines"
    )
    assert (
        index.adjacent_nonempty_panel("builtin_routines", forward=True)
        == "service_procs"
    )
    assert (
        index.adjacent_nonempty_panel("service_procs", forward=False)
        == "builtin_routines"
    )


def test_adjacent_nonempty_panel_skips_empty_panel() -> None:
    procs_only = build_services_panel_index(
        [ServiceProcItem(name="scheduler"), BgCmdItem(slot=1)]
    )
    assert procs_only.adjacent_nonempty_panel("service_procs", forward=True) is None
    assert procs_only.adjacent_nonempty_panel("service_procs", forward=False) is None
    routines_only = build_services_panel_index(
        [LumberjackItem(name="hooks")], _origins(hooks="builtin")
    )
    assert (
        routines_only.adjacent_nonempty_panel("builtin_routines", forward=True) is None
    )
    assert (
        routines_only.adjacent_nonempty_panel("builtin_routines", forward=False) is None
    )


def test_adjacent_nonempty_panel_empty_index_is_none() -> None:
    index = build_services_panel_index([])
    assert index.adjacent_nonempty_panel("service_procs", forward=True) is None
    assert index.adjacent_nonempty_panel("user_routines", forward=False) is None


def test_visible_keys_empty_shows_user_empty_state() -> None:
    index = build_services_panel_index([])
    assert index.visible_keys() == ["service_procs", "user_routines"]
    assert index.first_visible_routine_panel() == "user_routines"


def test_visible_keys_only_builtin() -> None:
    index = build_services_panel_index(
        [LumberjackItem(name="b")], _origins(b="builtin")
    )
    assert index.visible_keys() == ["service_procs", "builtin_routines"]
    assert index.first_visible_routine_panel() == "builtin_routines"


def test_visible_keys_only_user() -> None:
    index = build_services_panel_index([LumberjackItem(name="u")], _origins(u="user"))
    assert index.visible_keys() == ["service_procs", "user_routines"]
    assert index.first_visible_routine_panel() == "user_routines"


def test_visible_keys_all_three_sources() -> None:
    index = build_services_panel_index(
        [
            LumberjackItem(name="u"),
            LumberjackItem(name="p"),
            LumberjackItem(name="b"),
        ],
        _origins(u="user", p="plugin", b="builtin"),
    )
    assert index.visible_keys() == [
        "service_procs",
        "user_routines",
        "plugin_routines",
        "builtin_routines",
    ]
    assert index.first_visible_routine_panel() == "user_routines"


def test_first_visible_routine_panel_skips_empty_user() -> None:
    index = build_services_panel_index(
        [LumberjackItem(name="b")], _origins(b="builtin")
    )
    assert index.first_visible_routine_panel() == "builtin_routines"
