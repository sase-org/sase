"""Catalog fields the later Statistics CLI and TUI both read."""

from __future__ import annotations

from sase.ace.tui.modals.statistics_pane_data import (
    STATISTICS_VIEW_SPECS as TUI_VIEW_SPECS,
)
from sase.ace.tui.modals.statistics_pane_data import load_statistics_view as tui_load
from sase.ace.tui.modals.statistics_pane_legends import VIEW_LEGENDS as TUI_VIEW_LEGENDS
from sase.stats.loader import load_statistics_view
from sase.stats.registry import (
    MACROS_GROUP_ORDER,
    PERF_GROUP_ORDER,
    PROJECTS_GROUP_ORDER,
    STATISTICS_VIEW_SPECS,
    VIEW_LEGENDS,
    VIEW_ORDER,
    statistics_group_label,
    statistics_view_supports_grouping,
    validated_statistics_view,
)

_CLI_NAMES = {
    "overview": "overview",
    "runners": "runner",
    "projects": "project",
    "providers": "provider",
    "activity": "activity",
    "macros": "macro",
    "plans_questions": "plan",
    "perf": "perf",
}


def test_cli_name_maps_each_view_id_to_its_singular_noun() -> None:
    assert {spec.id: spec.cli_name for spec in STATISTICS_VIEW_SPECS} == _CLI_NAMES
    assert tuple(spec.id for spec in STATISTICS_VIEW_SPECS) == VIEW_ORDER


def test_project_report_constants_stay_off_the_live_spec() -> None:
    from sase.stats.registry import PROJECT_REPORT_GROUPINGS, PROJECT_REPORT_LEGENDS

    spec = {item.id: item for item in STATISTICS_VIEW_SPECS}["projects"]
    assert tuple(group.id for group in spec.groupings) == (
        "project",
        "patch",
        "drilldown",
    )
    assert {entry.term for entry in spec.legends} == {
        "Success",
        "Share",
        "Wall",
        "Patches",
        "✓/×",
        "Unattributed",
    }
    assert PROJECT_REPORT_GROUPINGS == ("project", "repo", "model", "patch")
    terms = {entry.term for entry in PROJECT_REPORT_LEGENDS}
    assert {"Commits", "Plans", "Runs", "?", "∅", "Coverage"} <= terms


def test_groupings_stay_on_the_pre_tui_ids() -> None:
    by_id = {spec.id: spec for spec in STATISTICS_VIEW_SPECS}
    assert tuple(group.id for group in by_id["projects"].groupings) == (
        "project",
        "patch",
        "drilldown",
    )
    assert tuple(group.id for group in by_id["macros"].groupings) == (
        "usage",
        "model",
        "project",
        "pairing",
    )
    assert tuple(group.id for group in by_id["perf"].groupings) == (
        "subsystem",
        "provider",
        "workflow",
    )
    assert PROJECTS_GROUP_ORDER == ("project", "patch", "drilldown")
    assert MACROS_GROUP_ORDER == ("usage", "model", "project", "pairing")
    assert PERF_GROUP_ORDER == ("subsystem", "provider", "workflow")
    for spec in STATISTICS_VIEW_SPECS:
        if spec.id in {"projects", "macros", "perf"}:
            assert statistics_view_supports_grouping(spec.id)
            continue
        assert spec.groupings == ()
        assert not statistics_view_supports_grouping(spec.id)


def test_legends_live_on_the_spec_and_the_view_lookup() -> None:
    for spec in STATISTICS_VIEW_SPECS:
        assert VIEW_LEGENDS[spec.id] == spec.legends
        assert spec.legends
    assert statistics_group_label("projects", "patch") == "By Patch"
    assert statistics_group_label("macros", "pairing") == "Used With"
    assert statistics_group_label("perf", "unknown") == "unknown"


def test_stored_retired_view_id_reads_as_macros() -> None:
    assert validated_statistics_view("xprompts") == "macros"
    assert validated_statistics_view("overview") == "overview"
    assert validated_statistics_view("nope") is None


def test_tui_shims_reexport_the_registry_and_loader() -> None:
    assert TUI_VIEW_SPECS is STATISTICS_VIEW_SPECS
    assert TUI_VIEW_LEGENDS is VIEW_LEGENDS
    assert tui_load is load_statistics_view
