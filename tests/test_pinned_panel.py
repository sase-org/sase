"""Tests for the pinned panel split feature."""

from __future__ import annotations

from sase.ace.tui.actions.agents._display import (
    _compute_pinned_panel_subtitle,
    _compute_pinned_panel_title,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList, PanelId
from sase.ace.tui.widgets import KeybindingFooter


def _make_agent(
    cl_name: str = "test_feature",
    status: str = "RUNNING",
    raw_suffix: str | None = "250101_120000",
) -> Agent:
    """Create a test Agent."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status=status,
        start_time=None,
        raw_suffix=raw_suffix,
    )


# --- AgentList panel identity ---


def test_agent_list_default_panel_is_main() -> None:
    """AgentList default panel identity is 'main'."""
    agent_list = AgentList()
    assert agent_list._panel == "main"


def test_agent_list_pinned_panel_identity() -> None:
    """AgentList accepts panel='pinned'."""
    agent_list = AgentList(panel="pinned")
    assert agent_list._panel == "pinned"


# --- SelectionChanged message ---


def test_selection_changed_carries_panel_main() -> None:
    """SelectionChanged message carries panel='main' by default."""
    msg = AgentList.SelectionChanged(index=3)
    assert msg.index == 3
    assert msg.panel == "main"


def test_selection_changed_carries_panel_pinned() -> None:
    """SelectionChanged message carries panel='pinned' when set."""
    msg = AgentList.SelectionChanged(index=1, panel="pinned")
    assert msg.index == 1
    assert msg.panel == "pinned"


# --- WidthChanged message ---


def test_width_changed_carries_panel() -> None:
    """WidthChanged message carries panel identity."""
    msg = AgentList.WidthChanged(width=50, panel="pinned")
    assert msg.width == 50
    assert msg.panel == "pinned"


# --- Footer bindings with pinned count ---


def test_footer_shows_pinned_switch_when_pinned_exist() -> None:
    """Footer shows panel switch binding when pinned agents exist."""
    footer = KeybindingFooter()
    agent = _make_agent(status="DONE")

    bindings = footer._compute_agent_bindings(agent, pinned_count=2, panel_focus="main")
    labels = [b[1] for b in bindings]
    assert "pinned" in labels


def test_footer_shows_list_switch_when_on_pinned_panel() -> None:
    """Footer shows 'list' label when focused on pinned panel."""
    footer = KeybindingFooter()
    agent = _make_agent(status="DONE")

    bindings = footer._compute_agent_bindings(
        agent, pinned_count=2, panel_focus="pinned"
    )
    labels = [b[1] for b in bindings]
    assert "list" in labels


def test_footer_no_pinned_switch_when_no_pinned() -> None:
    """Footer doesn't show panel switch when no pinned agents."""
    footer = KeybindingFooter()
    agent = _make_agent(status="DONE")

    bindings = footer._compute_agent_bindings(agent, pinned_count=0, panel_focus="main")
    labels = [b[1] for b in bindings]
    assert "pinned" not in labels
    assert "list" not in labels


def test_footer_none_agent_shows_pinned_switch() -> None:
    """Footer shows panel switch even with no agent selected."""
    footer = KeybindingFooter()

    bindings = footer._compute_agent_bindings(None, pinned_count=3, panel_focus="main")
    labels = [b[1] for b in bindings]
    assert "pinned" in labels


# --- Keymap integration ---


def test_focus_pinned_panel_in_default_config() -> None:
    """focus_pinned_panel action is wired in default config."""
    from sase.ace.tui.keymaps import load_keymap_registry

    reg = load_keymap_registry({})
    assert reg.app.focus_pinned_panel == "J"


def test_focus_pinned_panel_in_binding_meta() -> None:
    """focus_pinned_panel has a _BINDING_META entry."""
    from sase.ace.tui.keymaps import _BINDING_META

    actions = {a for a, _, _ in _BINDING_META}
    assert "focus_pinned_panel" in actions


# --- Dynamic title/subtitle ---


def test_pinned_panel_title_unfocused() -> None:
    """Unfocused pinned panel title shows count without ACTIVE."""
    title = _compute_pinned_panel_title(3, focused=False)
    assert "Pinned (3)" in title
    assert "ACTIVE" not in title


def test_pinned_panel_title_focused() -> None:
    """Focused pinned panel title includes ACTIVE indicator."""
    title = _compute_pinned_panel_title(2, focused=True)
    assert "Pinned (2)" in title
    assert "ACTIVE" in title


def test_pinned_panel_title_focused_has_bullet() -> None:
    """Focused title uses bullet separator before ACTIVE."""
    title = _compute_pinned_panel_title(1, focused=True)
    assert "\u2022" in title


def test_pinned_panel_subtitle_focused() -> None:
    """Focused pinned panel shows 'back to list' hint."""
    subtitle = _compute_pinned_panel_subtitle(2, focused=True)
    assert subtitle == "<J> back to list"


def test_pinned_panel_subtitle_unfocused_with_pinned() -> None:
    """Unfocused pinned panel with entries shows 'focus pinned' hint."""
    subtitle = _compute_pinned_panel_subtitle(2, focused=False)
    assert subtitle == "<J> focus pinned"


def test_pinned_panel_subtitle_unfocused_empty() -> None:
    """Unfocused empty pinned panel has no subtitle."""
    subtitle = _compute_pinned_panel_subtitle(0, focused=False)
    assert subtitle == ""


# --- Panel index building and focus fallback ---


def test_build_panel_indices_separates_pinned() -> None:
    """_build_panel_indices puts pinned+dismissable agents in pinned panel."""
    from sase.ace.tui.actions.agents._core import AgentsMixinCore

    agent_main = _make_agent(cl_name="main_agent", status="RUNNING")
    agent_pinned = _make_agent(cl_name="pinned_agent", status="DONE")

    class Stub:
        pass

    stub = Stub()
    stub._agents = [agent_main, agent_pinned]  # type: ignore[attr-defined]
    stub._pinned_agents = {agent_pinned.identity}  # type: ignore[attr-defined]

    AgentsMixinCore._build_panel_indices(stub)  # type: ignore[arg-type]

    assert stub._main_panel_indices == [0]  # type: ignore[attr-defined]
    assert stub._pinned_panel_indices == [1]  # type: ignore[attr-defined]
    assert stub._main_panel_idx_map == {0: 0}  # type: ignore[attr-defined]
    assert stub._pinned_panel_idx_map == {1: 0}  # type: ignore[attr-defined]


def test_build_panel_indices_running_pinned_stays_in_main() -> None:
    """A pinned agent that isn't in DISMISSABLE_STATUSES stays in main."""
    from sase.ace.tui.actions.agents._core import AgentsMixinCore

    agent = _make_agent(cl_name="running_pinned", status="RUNNING")

    class Stub:
        pass

    stub = Stub()
    stub._agents = [agent]  # type: ignore[attr-defined]
    stub._pinned_agents = {agent.identity}  # type: ignore[attr-defined]

    AgentsMixinCore._build_panel_indices(stub)  # type: ignore[arg-type]

    assert stub._main_panel_indices == [0]  # type: ignore[attr-defined]
    assert stub._pinned_panel_indices == []  # type: ignore[attr-defined]


def test_selection_continuity_on_pin() -> None:
    """Pinning preserves current_idx — the global index stays the same."""
    from sase.ace.tui.actions.agents._core import AgentsMixinCore

    agent_a = _make_agent(cl_name="agent_a", status="RUNNING")
    agent_b = _make_agent(cl_name="agent_b", status="DONE")

    class Stub:
        pass

    stub = Stub()
    stub._agents = [agent_a, agent_b]  # type: ignore[attr-defined]
    stub._pinned_agents = set()  # type: ignore[attr-defined]
    stub.current_idx = 1  # type: ignore[attr-defined]

    # Before pin: both in main
    AgentsMixinCore._build_panel_indices(stub)  # type: ignore[arg-type]
    assert stub._main_panel_indices == [0, 1]  # type: ignore[attr-defined]

    # Pin agent_b
    stub._pinned_agents.add(agent_b.identity)  # type: ignore[attr-defined]
    AgentsMixinCore._build_panel_indices(stub)  # type: ignore[arg-type]

    # current_idx unchanged, agent_b now in pinned panel
    assert stub.current_idx == 1  # type: ignore[attr-defined]
    assert 1 in stub._pinned_panel_idx_map  # type: ignore[attr-defined]


def test_selection_continuity_on_unpin() -> None:
    """Unpinning preserves current_idx — agent moves back to main."""
    from sase.ace.tui.actions.agents._core import AgentsMixinCore

    agent = _make_agent(cl_name="agent_x", status="DONE")

    class Stub:
        pass

    stub = Stub()
    stub._agents = [agent]  # type: ignore[attr-defined]
    stub._pinned_agents = {agent.identity}  # type: ignore[attr-defined]
    stub.current_idx = 0  # type: ignore[attr-defined]

    # Pinned state
    AgentsMixinCore._build_panel_indices(stub)  # type: ignore[arg-type]
    assert stub._pinned_panel_indices == [0]  # type: ignore[attr-defined]

    # Unpin
    stub._pinned_agents.clear()  # type: ignore[attr-defined]
    AgentsMixinCore._build_panel_indices(stub)  # type: ignore[arg-type]

    # current_idx unchanged, agent back in main
    assert stub.current_idx == 0  # type: ignore[attr-defined]
    assert 0 in stub._main_panel_idx_map  # type: ignore[attr-defined]
