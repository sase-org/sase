"""Behavioral coverage for the keyboard-first Update panel modal."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

import sase.ace.tui.modals.update_panel as update_panel_module
from sase.ace.tui.modals import UpdatePanel, UpdatePanelResult
from sase.ace.tui.update_panel_state import (
    UpdateOptionChip,
    UpdateOptionChipKind,
    UpdateOptionRow,
    UpdateOptionScope,
    UpdatePanelState,
)
from sase.ace.tui.widgets.update_accents import (
    AGENT_CLI_ACCENT,
    AGENTS_SYNC_ACCENT,
    CORE_UPDATE_ACCENT,
    UPDATES_ACCENT,
)

_SCOPES: tuple[UpdateOptionScope, ...] = (
    "everything",
    "sase",
    "providers",
    "agents",
)
_COPY: dict[UpdateOptionScope, tuple[str, str, str]] = {
    "everything": (
        "e",
        "Everything",
        "SASE, providers, and published agents in one tracked update.",
    ),
    "sase": (
        "s",
        "SASE, core & plugins",
        "Upgrade the sase host package, sase-core, and every installed plugin.",
    ),
    "providers": (
        "p",
        "Providers",
        "Update every installed LLM / agent CLI provider.",
    ),
    "agents": (
        "a",
        "Agents",
        "Import agent hoods your other machines published.",
    ),
}


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _row(
    scope: UpdateOptionScope,
    *,
    kind: UpdateOptionChipKind = "unknown",
    text: str = "· not checked yet",
    count: int = 0,
    detail: str | None = None,
    accent: str = UPDATES_ACCENT,
) -> UpdateOptionRow:
    key, title, description = _COPY[scope]
    return UpdateOptionRow(
        scope=scope,
        key=key,
        title=title,
        description=description,
        chip=UpdateOptionChip(kind=kind, text=text, count=count),
        detail=detail,
        accent=accent,
    )


def _state(
    *,
    freshness_label: str = "never checked — press r",
    stale: bool = True,
    rechecking: bool = False,
    rows: tuple[UpdateOptionRow, ...] | None = None,
) -> UpdatePanelState:
    if rows is None:
        rows = tuple(_row(scope) for scope in _SCOPES)
    return UpdatePanelState(
        rows=rows,
        freshness_label=freshness_label,
        stale=stale,
        rechecking=rechecking,
    )


def _populated_state() -> UpdatePanelState:
    return _state(
        freshness_label="4m ago",
        stale=False,
        rows=(
            _row(
                "everything",
                kind="available",
                text="↑ 6 available",
                count=6,
                accent="$primary",
            ),
            _row(
                "sase",
                kind="available",
                text="↑ 4 available",
                count=4,
                detail="sase 1 · sase-core 1 · plugins 2 · core rebuild",
                accent=CORE_UPDATE_ACCENT,
            ),
            _row(
                "providers",
                kind="available",
                text="↑ 2 available",
                count=2,
                detail="claude, codex · 1 needs manual steps",
                accent=AGENT_CLI_ACCENT,
            ),
            _row(
                "agents",
                kind="current",
                text="✓ up to date",
                accent=AGENTS_SYNC_ACCENT,
            ),
        ),
    )


def _prompt_plain(option: Any) -> str:
    console = Console(record=True, width=72, no_color=True, color_system=None)
    with console.capture() as capture:
        console.print(option.prompt)
    return capture.get()


def _plain(value: object) -> str:
    if isinstance(value, Text):
        return value.plain
    raw = str(value)
    try:
        return Text.from_markup(raw).plain
    except Exception:
        return raw


async def _push(pilot: Any, modal: UpdatePanel) -> list[UpdatePanelResult | None]:
    dismissed: list[UpdatePanelResult | None] = []
    pilot.app.push_screen(modal, callback=dismissed.append)
    await pilot.pause()
    return dismissed


def test_update_panel_is_exported_from_modals_package() -> None:
    assert UpdatePanel.__name__ == "UpdatePanel"
    assert UpdatePanelResult.__name__ == "UpdatePanelResult"


def test_update_panel_module_does_not_import_update_backends() -> None:
    source = Path(update_panel_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert all(
        not module.startswith(("sase.updates", "sase.agents_sync"))
        for module in modules
    )


async def test_letter_keys_dismiss_with_matching_scope() -> None:
    expected: dict[str, UpdateOptionScope] = {
        "e": "everything",
        "s": "sase",
        "p": "providers",
        "a": "agents",
    }
    for key, scope in expected.items():
        async with _TestApp().run_test(size=(100, 40)) as pilot:
            dismissed = await _push(pilot, UpdatePanel(_state()))
            await pilot.press(key)
            await pilot.pause()
        assert dismissed == [UpdatePanelResult(scope=scope, auto_approve=False)]


async def test_capital_keys_dismiss_with_auto_approve() -> None:
    expected: dict[str, UpdateOptionScope] = {
        "E": "everything",
        "S": "sase",
        "P": "providers",
        "A": "agents",
    }
    for key, scope in expected.items():
        async with _TestApp().run_test(size=(100, 40)) as pilot:
            dismissed = await _push(pilot, UpdatePanel(_state()))
            await pilot.press(key)
            await pilot.pause()
        assert dismissed == [UpdatePanelResult(scope=scope, auto_approve=True)]


async def test_enter_on_default_highlight_yields_everything() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        dismissed = await _push(pilot, UpdatePanel(_state()))
        await pilot.press("enter")
        await pilot.pause()
    assert dismissed == [UpdatePanelResult(scope="everything", auto_approve=False)]


async def test_jk_move_and_enter_follows_highlight() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = UpdatePanel(_state())
        dismissed = await _push(pilot, modal)
        option_list = modal.query_one("#update-panel-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 2

        await pilot.press("k")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("enter")
        await pilot.pause()
    assert dismissed == [UpdatePanelResult(scope="sase", auto_approve=False)]


async def test_escape_and_q_dismiss_none() -> None:
    for key in ("escape", "q"):
        async with _TestApp().run_test(size=(100, 40)) as pilot:
            dismissed = await _push(pilot, UpdatePanel(_state()))
            await pilot.press(key)
            await pilot.pause()
        assert dismissed == [None]


async def test_r_posts_recheck_without_dismissing() -> None:
    posted: list[object] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = UpdatePanel(_state())
        dismissed = await _push(pilot, modal)
        original = modal.post_message

        def _capture(message: object) -> bool:
            posted.append(message)
            return original(message)

        modal.post_message = _capture  # type: ignore[method-assign]
        await pilot.press("r")
        await pilot.pause()
        assert modal.query_one("#update-panel-list", OptionList).option_count == 4
    assert dismissed == []
    assert any(isinstance(message, UpdatePanel.RecheckRequested) for message in posted)


async def test_set_state_preserves_highlight() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = UpdatePanel(_state())
        dismissed = await _push(pilot, modal)
        await pilot.press("j")
        await pilot.pause()
        option_list = modal.query_one("#update-panel-list", OptionList)
        assert option_list.highlighted == 1

        modal.set_state(_populated_state())
        await pilot.pause()
        assert option_list.highlighted == 1
        assert option_list.option_count == 4
        prompt = _prompt_plain(option_list.get_option_at_index(1))
        assert "↑ 4 available" in prompt

        await pilot.press("enter")
        await pilot.pause()
    assert dismissed == [UpdatePanelResult(scope="sase", auto_approve=False)]


async def test_everything_row_keeps_key_and_chip_visible() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = UpdatePanel(_populated_state())
        dismissed = await _push(pilot, modal)
        option_list = modal.query_one("#update-panel-list", OptionList)
        prompt = option_list.get_option_at_index(0).prompt
        plain = _prompt_plain(option_list.get_option_at_index(0))
        assert plain.lstrip().startswith("e/E")
        assert "Everything" in plain
        assert "↑ 6 available" in plain
        assert modal._rich_accent("$primary") == ""
        if isinstance(prompt, Text):
            key_style = str(prompt.spans[0].style) if prompt.spans else ""
            assert "bold" in key_style
            assert "#" not in key_style
            capital_styles = " ".join(
                str(span.style) for span in prompt.spans if span.style is not None
            )
            assert CORE_UPDATE_ACCENT in capital_styles
        modal.action_cancel()
        await pilot.pause()
    assert dismissed == [None]


async def test_never_checked_state_renders_four_selectable_rows() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = UpdatePanel(_state())
        dismissed = await _push(pilot, modal)
        option_list = modal.query_one("#update-panel-list", OptionList)
        assert option_list.option_count == 4
        ids = [option_list.get_option_at_index(index).id for index in range(4)]
        assert ids == list(_SCOPES)
        assert all(
            not option_list.get_option_at_index(index).disabled for index in range(4)
        )
        everything = _prompt_plain(option_list.get_option_at_index(0))
        assert "Everything" in everything
        assert "e/E" in everything
        assert "· not checked yet" in everything
        paired = [
            _prompt_plain(option_list.get_option_at_index(index)) for index in range(4)
        ]
        assert all(
            label in prompt
            for prompt, label in zip(paired, ("e/E", "s/S", "p/P", "a/A"), strict=True)
        )
        hints = modal.query_one("#update-panel-hints", Static)
        hint_plain = _plain(hints.content)
        assert "preview" in hint_plain
        assert "apply now" in hint_plain
        assert "no prompt" in hint_plain
        assert "j/k move" in hint_plain
        assert "r re-check" in hint_plain
        await pilot.press("a")
        await pilot.pause()
    assert dismissed == [UpdatePanelResult(scope="agents", auto_approve=False)]


async def test_border_chrome_uses_freshness_rechecking_and_stale_accent() -> None:
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = UpdatePanel(
            _state(freshness_label="4m ago", stale=True, rechecking=False)
        )
        await _push(pilot, modal)
        container = modal.query_one("#update-panel-container", Container)
        assert _plain(container.border_title) == "↑ Update"
        subtitle = container.border_subtitle
        assert _plain(subtitle) == "4m ago"
        assert CORE_UPDATE_ACCENT in str(subtitle)
        assert container.has_class("-stale")

        modal.set_state(_state(freshness_label="4m ago", stale=False, rechecking=True))
        await pilot.pause()
        assert _plain(container.border_subtitle) == "re-checking…"
        assert not container.has_class("-stale")
        modal.action_cancel()
        await pilot.pause()


def test_option_selected_event_chooses_that_row(monkeypatch: Any) -> None:
    modal = UpdatePanel(_state())
    dismissed: list[object] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)
    option = Option("providers", id="providers")
    modal.on_option_list_option_selected(
        OptionList.OptionSelected(OptionList(), option, 2)
    )
    assert dismissed == [UpdatePanelResult(scope="providers", auto_approve=False)]


def test_choose_scope_dismisses_only_once(monkeypatch: Any) -> None:
    modal = UpdatePanel(_state())
    dismissed: list[object] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)
    modal._choose_scope("everything", auto_approve=False)
    modal._choose_scope("sase", auto_approve=True)
    assert dismissed == [UpdatePanelResult(scope="everything", auto_approve=False)]


def test_choose_scope_ignores_missing_row(monkeypatch: Any) -> None:
    modal = UpdatePanel(_state(rows=(_row("sase"),)))
    dismissed: list[object] = []
    monkeypatch.setattr(modal, "dismiss", dismissed.append)
    modal._choose_scope("everything", auto_approve=True)
    assert dismissed == []
