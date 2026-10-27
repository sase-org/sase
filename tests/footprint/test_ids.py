"""Tests for the Footprint feature ID scheme (``sase.footprint.ids``)."""

from __future__ import annotations

import pytest

from sase.footprint import ids


def test_valid_ids_match_pattern() -> None:
    for value in (
        "cli:bead.list",
        "cli:_root",
        "cli:bead.list#json",
        "cli:bead._1",
        "tui:app.zoom_panel",
        "tui:fold.cycle_hooks",
        "tui:statistics.cycle_range",
        "tui:artifacts.ref_plan",
        "view:tab.agents",
        "view:admin.statistics",
        "view:stats.footprint",
        "view:modal.add_macro",
        "macro:research",
        "macro:~custom",
        "skill:sase_repo",
        "config:ace.page_size",
        "auto:axe.housekeeping.notification_store_compact",
        "plugin:listen",
        "plugin:~third_party",
    ):
        assert ids.is_valid_feature_id(value), value


def test_invalid_ids_rejected() -> None:
    for value in (
        "",
        "cli:",
        ":bead.list",
        "CLI:bead.list",
        "cli:Bead.list",
        "cli:bead list",
        "cli:bead.list#json values",
        "cli:bead.+1",
        "tui:artifacts.ref:plan",
    ):
        assert not ids.is_valid_feature_id(value), value


def test_helpers_build_expected_ids() -> None:
    assert ids.cli_id([]) == "cli:_root"
    assert ids.cli_id(["bead", "list"]) == "cli:bead.list"
    assert ids.cli_id(["bead", "+1"]) == "cli:bead._1"
    assert ids.cli_option_id("cli:bead.list", "json") == "cli:bead.list#json"
    assert ids.tui_id("app", "zoom_panel") == "tui:app.zoom_panel"
    assert ids.tab_view_id("agents") == "view:tab.agents"
    assert ids.admin_view_id("statistics") == "view:admin.statistics"
    assert ids.stats_view_id("footprint") == "view:stats.footprint"
    assert ids.modal_id("AddMacroModal") == "view:modal.add_macro"
    assert ids.modal_id("AgentActionChooserModal") == (
        "view:modal.agent_action_chooser"
    )
    assert ids.modal_id("PlanApprovalScreen") == "view:modal.plan_approval"


def test_sanitize_maps_registry_names_to_valid_ids() -> None:
    assert ids.sanitize("+1") == "_1"
    assert ids.sanitize("ref:plan") == "ref_plan"
    assert ids.sanitize("bd/land_epic") == "bd_land_epic"
    assert ids.sanitize("builtin@https") == "builtin_https"
    for value in ("bead._1", "ref_plan", "json", "cycle_hooks"):
        assert ids.is_valid_feature_id(f"cli:{value}")


def test_navigation_actions_are_valid_app_ids() -> None:
    assert ids.NAVIGATION_ACTIONS
    for value in sorted(ids.NAVIGATION_ACTIONS):
        assert value.startswith("tui:app.")
        assert ids.is_valid_feature_id(value)


def test_first_party_plugins_are_valid() -> None:
    assert ids.FIRST_PARTY_PLUGIN_COMMANDS
    for word in ids.FIRST_PARTY_PLUGIN_COMMANDS:
        assert ids.is_valid_feature_id(f"plugin:{word}")


def test_cli_aliases_match_completion_compat_layer() -> None:
    from sase.completion.compat import get_completion_compat_aliases
    from sase.main.parser import create_parser
    import argparse

    parser = create_parser(only=None)
    top = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    by_id: dict[int, list[str]] = {}
    parser_by_id: dict[int, argparse.ArgumentParser] = {}
    for name, child in top.choices.items():
        by_id.setdefault(id(child), []).append(name)
        parser_by_id.setdefault(id(child), child)
    expected: dict[str, str] = {}
    for child_id, names in by_id.items():
        if len(names) < 2:
            continue
        compat = get_completion_compat_aliases(parser_by_id[child_id])
        canonical = next(name for name in names if name not in compat)
        for name in names:
            if name != canonical:
                expected[name] = canonical
    assert ids.CLI_ALIASES == expected


@pytest.mark.parametrize("ns", ids.NAMESPACES)
def test_namespaces_are_lowercase_alpha(ns: str) -> None:
    assert ns.isalpha() and ns.islower()
