"""Tests for the pinned panel split feature."""

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList
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


# --- _update_panel_focus_styling class toggling ---


class _FakeWidget:
    """Minimal widget stub for testing CSS class toggling."""

    def __init__(self) -> None:
        self.classes: set[str] = set()
        self.display: bool = True
        self.border_title: str = ""
        self.border_subtitle: str = ""

    def add_class(self, cls: str) -> None:
        self.classes.add(cls)

    def remove_class(self, cls: str) -> None:
        self.classes.discard(cls)

    def has_class(self, cls: str) -> bool:
        return cls in self.classes


class _FakeMixin:
    """Minimal mixin stub to test _update_panel_focus_styling in isolation."""

    def __init__(
        self,
        main_panel: _FakeWidget,
        pinned_container: _FakeWidget,
        pinned_panel_focused: str,
        pinned_panel_indices: list[int],
    ) -> None:
        self._main_panel = main_panel
        self._pinned_container = pinned_container
        self._pinned_panel_focused = pinned_panel_focused
        self._pinned_panel_indices = pinned_panel_indices

    def query_one(self, selector: str) -> _FakeWidget:
        if selector == "#agent-list-panel":
            return self._main_panel
        if selector == "#pinned-panel-container":
            return self._pinned_container
        raise ValueError(f"Unknown selector: {selector}")

    # Bind the real method
    from sase.ace.tui.actions.agents._display import AgentDisplayMixin

    _update_panel_focus_styling = AgentDisplayMixin._update_panel_focus_styling


def test_focus_main_sets_pinned_inactive() -> None:
    """When main is focused, pinned container gets panel-inactive class."""
    main = _FakeWidget()
    pinned = _FakeWidget()
    mixin = _FakeMixin(main, pinned, "main", [0, 1])
    mixin._update_panel_focus_styling()

    assert not main.has_class("panel-inactive")
    assert not pinned.has_class("panel-active")
    assert pinned.has_class("panel-inactive")


def test_focus_pinned_sets_main_inactive() -> None:
    """When pinned is focused, main panel gets panel-inactive class."""
    main = _FakeWidget()
    pinned = _FakeWidget()
    mixin = _FakeMixin(main, pinned, "pinned", [0, 1])
    mixin._update_panel_focus_styling()

    assert main.has_class("panel-inactive")
    assert pinned.has_class("panel-active")
    assert not pinned.has_class("panel-inactive")


def test_empty_pinned_hidden_no_inactive_class() -> None:
    """When pinned panel is empty, it's hidden and has no inactive class."""
    main = _FakeWidget()
    pinned = _FakeWidget()
    mixin = _FakeMixin(main, pinned, "main", [])
    mixin._update_panel_focus_styling()

    assert pinned.display is False
    assert not pinned.has_class("panel-inactive")
    assert not pinned.has_class("panel-active")


def test_border_title_and_subtitle_set() -> None:
    """Border title shows count and subtitle shows key hint."""
    main = _FakeWidget()
    pinned = _FakeWidget()
    mixin = _FakeMixin(main, pinned, "main", [0, 1, 2])
    mixin._update_panel_focus_styling()

    assert "3" in pinned.border_title
    assert "\U0001f4cc" in pinned.border_title
    assert pinned.border_subtitle == "J to switch"


def test_empty_pinned_no_subtitle() -> None:
    """When pinned is empty, no subtitle is set."""
    main = _FakeWidget()
    pinned = _FakeWidget()
    mixin = _FakeMixin(main, pinned, "main", [])
    mixin._update_panel_focus_styling()

    assert pinned.border_subtitle == ""
