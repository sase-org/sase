"""Tests for the pinned panel split feature."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList, PanelId
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.actions.agents._display import AgentDisplayMixin


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


# --- Panel focus styling (unit tests via mock widgets) ---


class _FakeWidget:
    """Minimal widget stub for focus-styling tests."""

    def __init__(self) -> None:
        self.classes: set[str] = set()
        self.display: bool = True
        self.border_title: str = ""
        self.border_subtitle: str = ""

    def add_class(self, cls: str) -> None:
        self.classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self.classes.discard(cls)


class _FakeMixin(AgentDisplayMixin):
    """Minimal mixin host for testing _update_panel_focus_styling."""

    def __init__(
        self,
        pinned_focused: str = "main",
        pinned_indices: list[int] | None = None,
    ) -> None:
        self._pinned_panel_focused = pinned_focused  # type: ignore[assignment]
        self._pinned_panel_indices = pinned_indices or []
        self._main_panel = _FakeWidget()
        self._pinned_container = _FakeWidget()
        self._keymap_registry = SimpleNamespace(
            app=SimpleNamespace(focus_pinned_panel="J")
        )

    def query_one(self, selector: str) -> _FakeWidget:  # type: ignore[override]
        if selector == "#agent-list-panel":
            return self._main_panel
        if selector == "#pinned-panel-container":
            return self._pinned_container
        raise ValueError(f"Unknown selector: {selector}")


def test_focus_styling_main_focused_classes() -> None:
    """When main is focused, pinned container gets panel-inactive, not panel-active."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[0, 1])
    with patch("sase.ace.tui.keymaps.loader.key_display_name", return_value="J"):
        mixin._update_panel_focus_styling()

    assert "panel-inactive" not in mixin._main_panel.classes
    assert "panel-inactive" in mixin._pinned_container.classes
    assert "panel-active" not in mixin._pinned_container.classes


def test_focus_styling_pinned_focused_classes() -> None:
    """When pinned is focused, pinned container gets panel-active, main gets panel-inactive."""
    mixin = _FakeMixin(pinned_focused="pinned", pinned_indices=[0, 1])
    with patch("sase.ace.tui.keymaps.loader.key_display_name", return_value="J"):
        mixin._update_panel_focus_styling()

    assert "panel-inactive" in mixin._main_panel.classes
    assert "panel-active" in mixin._pinned_container.classes
    assert "panel-inactive" not in mixin._pinned_container.classes


def test_focus_styling_hidden_when_empty() -> None:
    """Pinned container is hidden when there are no pinned indices."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[])
    mixin._update_panel_focus_styling()

    assert mixin._pinned_container.display is False


def test_focus_styling_visible_when_nonempty() -> None:
    """Pinned container is visible when pinned indices exist."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[0])
    with patch("sase.ace.tui.keymaps.loader.key_display_name", return_value="J"):
        mixin._update_panel_focus_styling()

    assert mixin._pinned_container.display is True


def test_focus_styling_border_title_count() -> None:
    """Border title includes the correct pinned count."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[0, 1, 2])
    with patch("sase.ace.tui.keymaps.loader.key_display_name", return_value="J"):
        mixin._update_panel_focus_styling()

    assert "(3)" in mixin._pinned_container.border_title
    assert "\U0001f4cc" in mixin._pinned_container.border_title


def test_focus_styling_border_subtitle_key_hint() -> None:
    """Border subtitle shows key hint when entries exist."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[0])
    with patch("sase.ace.tui.keymaps.loader.key_display_name", return_value="J"):
        mixin._update_panel_focus_styling()

    assert mixin._pinned_container.border_subtitle == "J switch"


def test_focus_styling_no_subtitle_when_empty() -> None:
    """Border subtitle is empty when no pinned entries."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[])
    mixin._update_panel_focus_styling()

    assert mixin._pinned_container.border_subtitle == ""


def test_focus_styling_class_toggle_round_trip() -> None:
    """Switching focus back and forth correctly toggles classes."""
    mixin = _FakeMixin(pinned_focused="main", pinned_indices=[0])
    with patch("sase.ace.tui.keymaps.loader.key_display_name", return_value="J"):
        mixin._update_panel_focus_styling()
        assert "panel-inactive" in mixin._pinned_container.classes

        # Switch to pinned
        mixin._pinned_panel_focused = "pinned"  # type: ignore[assignment]
        mixin._update_panel_focus_styling()
        assert "panel-active" in mixin._pinned_container.classes
        assert "panel-inactive" not in mixin._pinned_container.classes

        # Switch back to main
        mixin._pinned_panel_focused = "main"  # type: ignore[assignment]
        mixin._update_panel_focus_styling()
        assert "panel-inactive" in mixin._pinned_container.classes
        assert "panel-active" not in mixin._pinned_container.classes
