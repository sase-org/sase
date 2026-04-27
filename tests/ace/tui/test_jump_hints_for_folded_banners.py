"""Jump hints cover collapsed group banners on the Agents tab.

Pressing ``'`` should paint a ``[x]`` chip next to every collapsed banner
row alongside the visible-agent chips, so a single keystroke can either
land on an agent or focus a folded group banner. Expanded banners stay
hint-less because they are not selectable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _StubApp(AdvancedNavigationMixin):
    """Minimal harness for the agents-tab jump-mode helpers."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        collapsed: list[tuple[str, ...]] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = agents
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._current_group_key: tuple[str, ...] | None = None
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_last_index: dict[str, int] = {}
        self._entry_jump_last_agents_anchor: Any = None

    def _panel_keys_per_agent(self) -> list:
        from sase.ace.tui.models.agent_panels import panel_key_per_agent

        return panel_key_per_agent(self._agents)

    # The mixin would normally drive a full refresh; tests don't render so
    # we can swallow these calls.
    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        return

    def _refresh_current_tab(self) -> None:
        return

    def _update_jump_footer(self) -> None:
        return


def _agent(*, project: str, cl: str, name: str, tag: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
    )


def test_jump_targets_includes_collapsed_banners() -> None:
    """Targets list should contain a banner entry before its agent rows."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
        _agent(project="beta", cl="b1", name="b2"),
    ]
    # Collapse the alpha L0 banner so its single agent disappears and the
    # banner itself becomes a target.  beta agents stay visible.
    app = _StubApp(agents, collapsed=[("alpha",)])

    targets = app._jump_candidate_targets()

    assert ("banner", 0, ("alpha",)) in targets
    # The two beta agents are still visible.
    agent_targets = [t for t in targets if t[0] == "agent"]
    assert ("agent", 1) in agent_targets
    assert ("agent", 2) in agent_targets


def test_jump_targets_skips_expanded_banners() -> None:
    """Expanded banners contribute no target — only their agents do."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents)

    targets = app._jump_candidate_targets()

    banner_targets = [t for t in targets if t[0] == "banner"]
    assert banner_targets == []
    assert all(t[0] == "agent" for t in targets)


def test_jump_dispatch_banner_sets_group_key() -> None:
    """Selecting a banner hint sets ``_current_group_key`` without moving the agent."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1  # cursor sits on a beta agent
    app._begin_agents_jump_mode()

    # Find the hint allocated to the alpha banner target.
    banner_target = ("banner", 0, ("alpha",))
    hint = app._entry_jump_banner_to_hint[banner_target]

    handled = app._handle_entry_jump_key(hint)

    assert handled is True
    assert app._current_group_key == ("alpha",)
    # The agent index must not have moved — banner selection is purely
    # about the group highlight.
    assert app.current_idx == 1


def test_jump_dispatch_banner_switches_focused_panel() -> None:
    """Banner targets in a non-focused panel change ``focused_idx``."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tag="ws"),
    ]
    # Two panels: untagged (idx 0) and @ws (idx 1).
    app = _StubApp(agents, collapsed=[("alpha",)])
    assert app._panel_group.panel_keys == [None, "ws"]
    assert app._panel_group.focused_idx == 0

    app._begin_agents_jump_mode()

    # Pick out the banner hint that lives in panel 1 (the @ws panel).
    target = next(t for t in app._entry_jump_hint_to_banner.values() if t[1] == 1)
    hint = app._entry_jump_banner_to_hint[target]

    app._handle_entry_jump_key(hint)

    assert app._panel_group.focused_idx == 1
    assert app._current_group_key == target[2]


def test_back_jump_restores_agent_anchor() -> None:
    """``'`` after an agent→banner jump returns to the original agent."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1  # cursor starts on the beta agent

    # First press: pick the alpha banner.
    app._begin_agents_jump_mode()
    banner_hint = next(iter(app._entry_jump_hint_to_banner))
    app._handle_entry_jump_key(banner_hint)
    assert app._current_group_key == ("alpha",)

    # Second press: ``'`` again should restore the prior agent cursor.
    app._begin_agents_jump_mode()
    app._handle_entry_jump_key("apostrophe")

    assert app._current_group_key is None
    assert app.current_idx == 1
