"""Tests for the leader ``,L`` Log panel keymap wiring (Phase 2)."""

from __future__ import annotations

import pytest

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.keymaps.types import LeaderModeKeymaps
from sase.ace.tui.widgets import KeybindingFooter

from tests.ace.tui._leader_keymap_helpers import (
    _capture_bindings,
    _FakeApp,
    _last_keys,
    _last_labels,
    _make_cs,
)


def test_default_config_binds_leader_l_to_log_panel() -> None:
    registry = load_keymap_registry({})

    assert registry.leader_mode.keys["log_panel"] == "L"


def test_types_factory_default_matches_config() -> None:
    # config/types parity: the dataclass factory and default_config.yml agree.
    assert LeaderModeKeymaps().keys["log_panel"] == "L"
    assert load_keymap_registry({}).leader_mode.keys["log_panel"] == "L"


def test_leader_l_is_free_of_collisions() -> None:
    keys = load_keymap_registry({}).leader_mode.keys
    owners = [name for name, value in keys.items() if value == "L"]

    assert owners == ["log_panel"]


@pytest.mark.parametrize("tab", ["changespecs", "agents", "axe"])
def test_leader_l_opens_log_panel_from_every_tab(tab: str) -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")], current_tab=tab)

    handled = app._handle_leader_key("L")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.log_panel_count == 1
    assert app._last_leader_key == "L"
    assert app.refresh_count == 1


def test_leader_l_repeat_reopens_log_panel() -> None:
    app = _FakeApp(current_tab="agents")

    app._handle_leader_key("L")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "L"
    assert app.log_panel_count == 2


def test_footer_surfaces_log_panel_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "L" in _last_keys(captured)
        assert "log panel" in _last_labels(captured)
