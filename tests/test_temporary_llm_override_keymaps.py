"""Cross-source keymap, footer, and help sync for temporary LLM overrides."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)
from sase.ace.tui.widgets import KeybindingFooter

from tests._temporary_llm_override_helpers import flatten_help_keys, full_registry


@pytest.mark.parametrize(
    "build_sections",
    [cls_bindings, agents_bindings],
)
def test_help_modal_includes_temporary_override_on_main_tabs(
    build_sections,
) -> None:
    """``,o`` "Model overrides" appears in changespecs and agents help."""
    reg = full_registry()
    sections = build_sections(reg)
    flat = flatten_help_keys(sections)
    assert ",o|Model overrides" in flat


def test_help_modal_axe_tab_includes_temporary_override() -> None:
    """The axe tab also surfaces ``,o`` in its leader-mode block."""
    reg = full_registry()
    sections = axe_bindings(reg)
    flat = flatten_help_keys(sections)
    assert ",o|Model overrides" in flat


def test_help_modal_keybinding_uses_configured_leader_prefix() -> None:
    """When the leader prefix is overridden, the help text reflects it."""
    reg = full_registry(
        {"keymaps": {"modes": {"leader_mode": {"prefix": "semicolon"}}}}
    )
    sections = cls_bindings(reg)
    flat = flatten_help_keys(sections)
    assert ";o|Model overrides" in flat


def test_help_modal_keybinding_uses_configured_temporary_key() -> None:
    """When the chord key is overridden, the help text reflects it."""
    reg = full_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {"keys": {"temporary_llm_override": "T"}},
                },
            },
        }
    )
    sections = cls_bindings(reg)
    flat = flatten_help_keys(sections)
    assert ",T|Model overrides" in flat


def test_footer_leader_bindings_include_temporary_override() -> None:
    """``update_leader_bindings`` puts ``o model overrides`` in the footer."""
    footer = KeybindingFooter()
    captured: list[tuple[list[tuple[str, str]], str | None]] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda bindings, mode_label=None: captured.append(
            (list(bindings), mode_label)
        )
    )

    footer.update_leader_bindings(current_tab="changespecs")

    assert captured, "footer never updated"
    bindings, mode_label = captured[-1]
    assert mode_label == "LEADER"
    assert any(label == "model overrides" for _, label in bindings)


@pytest.mark.parametrize("tab", ["changespecs", "agents", "axe"])
def test_footer_leader_bindings_present_on_every_tab(tab: str) -> None:
    """Every tab's footer surfaces the override action in leader mode."""
    footer = KeybindingFooter()
    captured: list[tuple[list[tuple[str, str]], str | None]] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda bindings, mode_label=None: captured.append(
            (list(bindings), mode_label)
        )
    )

    footer.update_leader_bindings(current_tab=tab)

    bindings, _ = captured[-1]
    assert any(label == "model overrides" for _, label in bindings)
