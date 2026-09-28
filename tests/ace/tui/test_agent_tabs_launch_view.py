"""Launch-from-view (R1) submit insertion and landing-toast helpers."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agent_workflow._launch_prompt_inputs import (
    LaunchPromptInputMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_submission import (
    LaunchSubmissionMixin,
)
from sase.ace.tui.agent_tabs_launch_view import (
    active_machine_tab_alias,
    view_inherited_tab_name,
)
from sase.ace.tui.models.agent_tab_index import AgentTabCatalogEntry
from sase.core.agent_tab import AgentTabKey


def _view(tab: AgentTabKey, *, current: str = "agents") -> SimpleNamespace:
    return SimpleNamespace(current_tab=current, _active_agent_tab=tab)


def test_view_inherited_tab_name_from_named_tab() -> None:
    assert view_inherited_tab_name(_view(AgentTabKey.named("blog"))) == "blog"


def test_view_inherited_tab_name_opt_outs() -> None:
    assert view_inherited_tab_name(_view(AgentTabKey.default())) is None
    assert view_inherited_tab_name(_view(AgentTabKey.machine("iid"))) is None
    assert (
        view_inherited_tab_name(_view(AgentTabKey.named("blog"), current="artifacts"))
        is None
    )


def test_view_inherited_tab_name_respects_config_off(
    monkeypatch,
) -> None:
    import sase.ace.tui.agent_tabs_launch_view as launch_view

    monkeypatch.setattr(launch_view, "launch_from_view_enabled", lambda: False)
    assert view_inherited_tab_name(_view(AgentTabKey.named("blog"))) is None


def test_active_machine_tab_alias() -> None:
    key = AgentTabKey.machine("iid-apollo")
    app = _view(key)
    app._agent_tab_index = SimpleNamespace(
        catalog=(
            AgentTabCatalogEntry(AgentTabKey.default(), "default", "⌨ local", 1),
            AgentTabCatalogEntry(key, "machine", "⌨ apollo", 2),
        )
    )
    app._agent_tab_latched_key = None
    assert active_machine_tab_alias(app) == "apollo"


def test_active_machine_tab_alias_opt_outs() -> None:
    assert active_machine_tab_alias(_view(AgentTabKey.default())) is None
    assert active_machine_tab_alias(_view(AgentTabKey.named("apollo"))) is None


def test_apply_launch_view_tab_inserts_from_named_view() -> None:
    out = LaunchPromptInputMixin._apply_launch_view_tab(
        _view(AgentTabKey.named("blog")), "do work"
    )
    assert out == "%tab:blog\ndo work"


def test_apply_launch_view_tab_skips() -> None:
    same = LaunchPromptInputMixin._apply_launch_view_tab(
        _view(AgentTabKey.named("blog")), "%tab:main\ndo work"
    )
    assert same == "%tab:main\ndo work"
    default_view = LaunchPromptInputMixin._apply_launch_view_tab(
        _view(AgentTabKey.default()), "do work"
    )
    assert default_view == "do work"
    machine_view = LaunchPromptInputMixin._apply_launch_view_tab(
        _view(AgentTabKey.machine("iid")), "do work"
    )
    assert machine_view == "do work"
    swarm = LaunchPromptInputMixin._apply_launch_view_tab(
        _view(AgentTabKey.named("blog")), "one\n---\n%tab:sase\ntwo"
    )
    assert swarm == "%tab:blog\none\n---\n%tab:sase\ntwo"


def test_launch_destination_tab_marks_arrival() -> None:
    arrivals: set[AgentTabKey] = set()
    app = _view(AgentTabKey.default())
    app._agent_tab_arrivals = arrivals
    dest = LaunchSubmissionMixin._launch_destination_tab(app, "%tab:blog\ndo work")
    assert dest == "blog"
    assert AgentTabKey.named("blog") in arrivals


def test_launch_destination_tab_same_tab_is_quiet() -> None:
    arrivals: set[AgentTabKey] = set()
    app = _view(AgentTabKey.named("blog"))
    app._agent_tab_arrivals = arrivals
    assert (
        LaunchSubmissionMixin._launch_destination_tab(app, "%tab:blog\ndo work") is None
    )
    assert LaunchSubmissionMixin._launch_destination_tab(app, "do work") is None
    assert not arrivals
