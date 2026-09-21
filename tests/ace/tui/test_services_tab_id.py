"""Canonical Services tab id with ``axe`` as a normalized legacy alias."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.commands._tabs import AXE_ONLY
from sase.ace.tui.commands.availability import is_command_available
from sase.ace.tui.commands.types import CommandContext, CommandExecutor, CommandSpec
from sase.ace.tui.keymaps import footer_key_display
from sase.ace.tui.tab_order import (
    SERVICES_TAB,
    TAB_ORDER,
    normalize_tab_name,
)
from sase.ace.tui.widgets import KeybindingFooter


def test_services_tab_id_is_canonical() -> None:
    assert SERVICES_TAB == "services"
    assert TAB_ORDER == ("agents", "artifacts", "services")
    assert "axe" not in TAB_ORDER
    assert normalize_tab_name("axe") == "services"
    assert normalize_tab_name("services") == "services"
    assert normalize_tab_name(None) == "agents"


async def test_legacy_axe_initial_tab_lands_on_services() -> None:
    async with AcePage(initial_tab="axe") as page:  # legacy compatibility alias
        await page.expect_state("tab", "axe")  # legacy alias proves the funnel
        assert page.app.current_tab == "services"
        assert page.app.current_tab != "agents"
        assert not page.app.query_one("#axe-view").has_class("hidden")
        assert page.app.query_one("#agents-view").has_class("hidden")


def test_ace_app_constructed_with_legacy_axe_tab_normalizes() -> None:
    app = AceApp(query="!!!", auto_start_axe=False, initial_tab="axe")  # legacy alias
    assert app.current_tab == "services"


def test_command_context_normalizes_legacy_axe_tab() -> None:
    ctx = CommandContext(tab="axe")  # legacy compatibility alias
    assert ctx.tab == "services"
    spec = CommandSpec(
        id="app.add_axe_item",
        label="Add",
        key_sequence=("a",),
        key_display="a",
        category="Axe",
        tabs=AXE_ONLY,
        executor=CommandExecutor(kind="app_action", action="add_axe_item"),
    )
    assert spec.tabs == ("services",)
    assert is_command_available(spec, ctx)


def test_services_copy_footer_resolves_axe_keymap_group() -> None:
    footer = KeybindingFooter()
    footer.update_copy_bindings(tab="services")
    assert footer._last_layout_inputs is not None
    bindings, mode_label = footer._last_layout_inputs
    assert mode_label == "COPY"
    assert bindings, "Services-tab copy footer must resolve the axe keymap group"
    registry = footer._kr()
    axe_keys = {
        footer_key_display(value)
        for value in registry.copy_mode.keys["axe"].values()
        if isinstance(value, str)
    }
    shown = {key for key, _label in bindings}
    assert shown, "expected at least one visible Services copy binding"
    assert shown <= axe_keys


def test_cli_legacy_axe_tab_normalizes_to_services() -> None:
    from sase.main.parser import create_parser

    # NOTE: the plan named ["ace", ...] here, but "ace" is not a registered
    # top-level subcommand (only "tui" is); legacy "ace" argv is rewritten to
    # "tui" by the restart path, so the live spelling is tested instead.
    args = create_parser().parse_args(["tui", "--tab", "axe"])
    assert args.tab == "axe"
    assert normalize_tab_name(args.tab) == "services"
