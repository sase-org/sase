"""Agents-tab metadata fold dispatch and footer tests."""

from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.navigation._fold import FoldNavigationMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.fold_state import (
    FoldLevel,
    SectionFoldStateManager,
)
from sase.ace.tui.widgets import KeybindingFooter


class _FoldApp(FoldNavigationMixin):
    def __init__(self, *, tab: str = "agents", clan: bool = True) -> None:
        self.current_tab = tab
        self._fold_mode_active = False
        self._keymap_registry = load_keymap_registry({})
        self.panel_fold_level = FoldLevel.COLLAPSED
        self._panel_fold_overrides = SectionFoldStateManager()
        self.commits_collapsed = FoldLevel.COLLAPSED
        self.hooks_collapsed = FoldLevel.COLLAPSED
        self.mentors_collapsed = FoldLevel.COLLAPSED
        self.timestamps_collapsed = FoldLevel.COLLAPSED
        self.deltas_collapsed = FoldLevel.COLLAPSED
        self.section_id: str | None = "errors"
        self.selected_agent = SimpleNamespace(is_clan_container=clan)
        self.refresh_count = 0
        self.notifications: list[str] = []

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def _current_agent_metadata_section_id(self) -> str | None:
        return self.section_id

    def _get_selected_agent(self) -> object:
        return self.selected_agent

    def notify(self, message: str) -> None:
        self.notifications.append(message)


def _press(app: _FoldApp, key: str) -> None:
    app._fold_mode_active = True
    assert app._handle_fold_key(key) is True
    assert app._fold_mode_active is False


def test_agents_panel_level_cycles_forward_backward_and_clears_overrides() -> None:
    app = _FoldApp()
    app._panel_fold_overrides.set("errors", FoldLevel.FULLY_EXPANDED)

    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.EXPANDED
    assert app._panel_fold_overrides.snapshot() == {}

    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.FULLY_EXPANDED
    _press(app, "z")
    assert app.panel_fold_level is FoldLevel.COLLAPSED

    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.FULLY_EXPANDED
    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.EXPANDED
    _press(app, "Z")
    assert app.panel_fold_level is FoldLevel.COLLAPSED


def test_agents_section_cycle_and_toggle_use_effective_panel_level() -> None:
    app = _FoldApp()

    _press(app, "a")
    assert app._panel_fold_overrides.get_override("errors") is FoldLevel.EXPANDED

    _press(app, "A")
    assert app._panel_fold_overrides.get_override("errors") is FoldLevel.COLLAPSED
    _press(app, "A")
    assert app._panel_fold_overrides.get_override("errors") is (
        FoldLevel.FULLY_EXPANDED
    )


def test_agents_section_fold_noops_without_a_current_cached_section() -> None:
    app = _FoldApp()
    app.section_id = None

    _press(app, "a")

    assert app._panel_fold_overrides.snapshot() == {}
    assert app.refresh_count == 1


def test_agents_fold_does_not_mutate_changespec_fold_state() -> None:
    app = _FoldApp()

    _press(app, "z")

    assert app.commits_collapsed is FoldLevel.COLLAPSED
    assert app.hooks_collapsed is FoldLevel.COLLAPSED


def test_changespec_fold_dispatch_remains_unchanged() -> None:
    app = _FoldApp(tab="changespecs")

    _press(app, "c")

    assert app.commits_collapsed is FoldLevel.EXPANDED
    assert app.panel_fold_level is FoldLevel.COLLAPSED


def test_regular_agent_fold_change_shows_scope_toast_but_clan_does_not() -> None:
    regular = _FoldApp(clan=False)
    clan = _FoldApp(clan=True)

    _press(regular, "z")
    _press(clan, "z")

    assert regular.notifications == ["Fold levels currently shape clan summaries"]
    assert clan.notifications == []


def test_agents_fold_footer_uses_nested_agent_submap() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(current_tab="agents")

    assert update.call_args.args == (
        [
            ("z", "level forward"),
            ("Z", "level back"),
            ("a", "section forward"),
            ("A", "toggle section"),
        ],
    )
    assert update.call_args.kwargs == {"mode_label": "FOLD"}
