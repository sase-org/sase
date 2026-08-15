"""Cross-source keymap, footer, and help sync for the Launch Control (``,m``).

Phase 2 (epic sase-5e): the leader ``,m`` action was renamed
``temporary_llm_override`` → ``models_panel`` and now opens the Launch Control.
These tests pin that the typed defaults, bundled YAML, ``?`` help modal, and
footer all agree.
"""

from __future__ import annotations

import importlib.resources
from unittest.mock import MagicMock

import pytest
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.keymaps.types import LeaderModeKeymaps
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)
from sase.ace.tui.widgets import KeybindingFooter

from tests._temporary_llm_override_helpers import flatten_help_keys, full_registry


# ---------------------------------------------------------------------------
# Default keymap exposes the renamed chord
# ---------------------------------------------------------------------------


def test_leader_default_includes_models_panel() -> None:
    leader = LeaderModeKeymaps()
    assert leader.keys["models_panel"] == "m"
    assert "temporary_llm_override" not in leader.keys


def test_leader_default_in_yaml() -> None:
    text = (
        importlib.resources.files("sase")
        .joinpath("default_config.yml")
        .read_text(encoding="utf-8")
    )
    data = yaml.safe_load(text)
    leader = data["ace"]["keymaps"]["modes"]["leader_mode"]["keys"]
    assert leader["models_panel"] == "m"
    assert "temporary_llm_override" not in leader


# ---------------------------------------------------------------------------
# Help modal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build_sections", [cls_bindings, agents_bindings])
def test_help_modal_includes_models_panel_on_main_tabs(build_sections) -> None:
    reg = full_registry()
    flat = flatten_help_keys(build_sections(reg))
    assert ",m|Launch Control" in flat


def test_help_modal_axe_tab_includes_models_panel() -> None:
    reg = full_registry()
    flat = flatten_help_keys(axe_bindings(reg))
    assert ",m|Launch Control" in flat


def test_help_modal_keybinding_uses_configured_leader_prefix() -> None:
    reg = full_registry(
        {"keymaps": {"modes": {"leader_mode": {"prefix": "semicolon"}}}}
    )
    flat = flatten_help_keys(cls_bindings(reg))
    assert ";m|Launch Control" in flat


def test_help_modal_keybinding_uses_configured_models_panel_key() -> None:
    reg = full_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"models_panel": "P"}}}}}
    )
    flat = flatten_help_keys(cls_bindings(reg))
    assert ",P|Launch Control" in flat


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def _capture_footer(tab: str) -> list[tuple[str, str]]:
    footer = KeybindingFooter()
    captured: list[tuple[list[tuple[str, str]], str | None]] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda bindings, mode_label=None: captured.append(
            (list(bindings), mode_label)
        )
    )
    footer.update_leader_bindings(current_tab=tab)
    assert captured, "footer never updated"
    return captured[-1][0]


def test_footer_leader_bindings_include_models_panel() -> None:
    bindings = _capture_footer("changespecs")  # legacy wire key
    assert any(label == "Launch Control" for _, label in bindings)


@pytest.mark.parametrize("tab", ["changespecs", "agents", "axe"])  # legacy wire key
def test_footer_leader_bindings_present_on_every_tab(tab: str) -> None:
    bindings = _capture_footer(tab)
    assert any(label == "Launch Control" for _, label in bindings)


def test_models_panel_includes_bucket_drill_bindings() -> None:
    bindings = {(binding[0], binding[1]) for binding in ModelsPanel.BINDINGS}
    assert ("l", "enter_bucket") in bindings
    assert ("right", "enter_bucket") in bindings
    assert ("h", "leave_bucket") in bindings
    assert ("left", "leave_bucket") in bindings
    assert ("ctrl+r", "manage_runner_limit") in bindings
