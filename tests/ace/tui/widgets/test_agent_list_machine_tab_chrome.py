"""Machine-tab chrome suppression: redundant chips and lone banners."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.widgets._agent_list_build_rows import (
    build_row_inputs,
    _machine_tab_chrome_suppressed,
    suppress_lone_machine_banner,
)
from sase.core.agent_tab import AgentTabKey, DEFAULT_AGENT_TAB_KEY
from sase.feature_flags import override_flags

from ._agent_list_grouping_helpers import make_agent


def _machine_app() -> SimpleNamespace:
    return SimpleNamespace(
        _active_agent_tab=AgentTabKey.machine("iid-apollo"),
    )


def test_chrome_suppression_off_with_flag_off() -> None:
    with override_flags(agent_tabs=False):
        assert _machine_tab_chrome_suppressed(_machine_app()) is False
        assert _machine_tab_chrome_suppressed(None) is False


def test_chrome_suppression_on_machine_tabs() -> None:
    with override_flags(agent_tabs=True):
        assert _machine_tab_chrome_suppressed(_machine_app()) is True
        unresolved = SimpleNamespace(
            _active_agent_tab=AgentTabKey.unresolved_machine("apollo"),
        )
        assert _machine_tab_chrome_suppressed(unresolved) is True


def test_chrome_suppression_default_tab_follows_machine_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui import agent_tabs_settings as settings_mod

    app = SimpleNamespace(_active_agent_tab=DEFAULT_AGENT_TAB_KEY)
    with override_flags(agent_tabs=True):
        monkeypatch.setattr(
            settings_mod,
            "agent_tabs_view_config",
            lambda: SimpleNamespace(machine_mode=True),
        )
        assert _machine_tab_chrome_suppressed(app) is True
        monkeypatch.setattr(
            settings_mod,
            "agent_tabs_view_config",
            lambda: SimpleNamespace(machine_mode=False),
        )
        assert _machine_tab_chrome_suppressed(app) is False


def test_chrome_suppression_keeps_named_tabs_and_all() -> None:
    with override_flags(agent_tabs=True):
        named = SimpleNamespace(_active_agent_tab=AgentTabKey.named("sase"))
        assert _machine_tab_chrome_suppressed(named) is False
        assert _machine_tab_chrome_suppressed(SimpleNamespace()) is False


def test_row_inputs_hide_machine_chip_on_machine_tab() -> None:
    remote = make_agent(cl_name="remote-fix")
    remote.fleet_origin_alias = "apollo"
    widget = SimpleNamespace(app=_machine_app())
    with override_flags(agent_tabs=True):
        inputs = build_row_inputs(
            widget,
            [remote],
            0,
            marked_agents=None,
            unread_agents=None,
            fold_restore_marked_keys=None,
            fold_counts=None,
            jump_hints=None,
            current_group_key=None,
            tribe_labels=None,
            panel_tribe=None,
            parents_with_visible_children=None,
            fully_expanded_parents=None,
            now=None,
        )
        assert inputs.show_machine_chip is False


def test_row_inputs_keep_machine_chip_on_named_tab() -> None:
    remote = make_agent(cl_name="remote-fix")
    remote.fleet_origin_alias = "apollo"
    widget = SimpleNamespace(
        app=SimpleNamespace(_active_agent_tab=AgentTabKey.named("sase"))
    )
    with override_flags(agent_tabs=True):
        inputs = build_row_inputs(
            widget,
            [remote],
            0,
            marked_agents=None,
            unread_agents=None,
            fold_restore_marked_keys=None,
            fold_counts=None,
            jump_hints=None,
            current_group_key=None,
            tribe_labels=None,
            panel_tribe=None,
            parents_with_visible_children=None,
            fully_expanded_parents=None,
            now=None,
        )
        assert inputs.show_machine_chip is True


def test_lone_machine_banner_drops_on_machine_tab() -> None:
    local = make_agent(cl_name="local-fix")
    tree = build_agent_tree([local], mode=GroupingMode.BY_MACHINE)
    assert (
        sum(
            1
            for e in tree
            if e.kind == "group" and e.group is not None and e.group.level == 0
        )
        == 1
    )
    with override_flags(agent_tabs=True):
        filtered = suppress_lone_machine_banner(
            tree, grouping_mode=GroupingMode.BY_MACHINE, app=_machine_app()
        )
    assert all(
        not (e.kind == "group" and e.group is not None and e.group.level == 0)
        for e in filtered
    )
    # The L1 status subgroup stays.
    assert any(e.kind == "group" for e in filtered)


def test_lone_machine_banner_kept_off_machine_tabs() -> None:
    local = make_agent(cl_name="local-fix")
    remote = make_agent(cl_name="remote-fix")
    remote.fleet_origin_alias = "apollo"
    tree = build_agent_tree([local], mode=GroupingMode.BY_MACHINE)
    named_app = SimpleNamespace(_active_agent_tab=AgentTabKey.named("sase"))
    with override_flags(agent_tabs=True):
        assert (
            suppress_lone_machine_banner(
                tree, grouping_mode=GroupingMode.BY_MACHINE, app=named_app
            )
            == tree
        )
        assert (
            suppress_lone_machine_banner(
                tree, grouping_mode=GroupingMode.STANDARD, app=_machine_app()
            )
            == tree
        )
    with override_flags(agent_tabs=False):
        assert (
            suppress_lone_machine_banner(
                tree, grouping_mode=GroupingMode.BY_MACHINE, app=_machine_app()
            )
            == tree
        )
    # Two machines on one tab keep both banners.
    two_tree = build_agent_tree([local, remote], mode=GroupingMode.BY_MACHINE)
    with override_flags(agent_tabs=True):
        assert (
            suppress_lone_machine_banner(
                two_tree, grouping_mode=GroupingMode.BY_MACHINE, app=_machine_app()
            )
            == two_tree
        )
