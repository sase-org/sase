"""Tests for the pinned panel split feature."""

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
