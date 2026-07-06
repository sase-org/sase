"""Tests for the Frontmatter Panel structured sub-form modals (Phase 4).

Covers the ``input`` and ``xprompts`` item editors: the pure compact-input-spec
parser/serializer and local-name validator, plus interactive build → save → cancel
flows with live validation gating.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.modals.input_item_modal import InputItemModal, default_to_text
from sase.ace.tui.modals.xprompt_item_modal import (
    XPromptItemModal,
    _format_compact_input_specs,
    _parse_compact_input_specs,
    _validate_local_xprompt_name,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.models import UNSET, InputArg, InputType, XPrompt


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


# --- pure: compact input specs ---------------------------------------------


def test_parse_compact_specs_covers_all_forms() -> None:
    specs = _parse_compact_input_specs("target:word, dry_run:bool=false, retries:int=3")
    assert [(s.name, s.type, s.default) for s in specs] == [
        ("target", InputType.WORD, UNSET),
        ("dry_run", InputType.BOOL, False),
        ("retries", InputType.INT, 3),
    ]


def test_parse_compact_specs_defaults_to_line_and_accepts_aliases() -> None:
    specs = _parse_compact_input_specs("note, count:integer=2")
    assert specs[0].type is InputType.LINE
    assert specs[0].default is UNSET
    assert specs[1].type is InputType.INT
    assert specs[1].default == 2


def test_parse_compact_specs_round_trips_through_format() -> None:
    text = "target:word, dry_run:bool=false, retries:int=3"
    assert _format_compact_input_specs(_parse_compact_input_specs(text)) == text


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("bad name:word", "invalid input name"),
        ("svc:notatype", "unknown input type"),
        ("retries:int=nope", "expects int"),
        ("dup:word, dup:int", "duplicate input"),
    ],
)
def test_parse_compact_specs_rejects_bad_input(text: str, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        _parse_compact_input_specs(text)


def test_default_to_text_renders_bool_and_scalar() -> None:
    assert default_to_text(False) == "false"
    assert default_to_text(True) == "true"
    assert default_to_text(3) == "3"
    assert default_to_text(UNSET) == ""


# --- pure: local xprompt name validation -----------------------------------


def test_validate_local_xprompt_name_enforces_underscore() -> None:
    assert _validate_local_xprompt_name("_rules") == ""
    assert "must start with '_'" in _validate_local_xprompt_name("rules")
    assert _validate_local_xprompt_name("") == "name is required"


# --- interactive: input item modal -----------------------------------------


async def test_input_modal_saves_constructed_arg() -> None:
    result: object = "sentinel"
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = InputItemModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#input-item-name", SingleLineVimTextArea).text = "service"
        modal.query_one("#input-item-type", SingleLineVimTextArea).text = "word"
        modal.query_one("#input-item-default", SingleLineVimTextArea).text = ""
        modal.query_one(
            "#input-item-description", SingleLineVimTextArea
        ).text = "target service"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()

    assert isinstance(result, InputArg)
    assert result.name == "service"
    assert result.type is InputType.WORD
    assert result.default is UNSET
    assert result.description == "target service"


async def test_input_modal_coerces_typed_default() -> None:
    result: object = None
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = InputItemModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#input-item-name", SingleLineVimTextArea).text = "retries"
        modal.query_one("#input-item-type", SingleLineVimTextArea).text = "int"
        modal.query_one("#input-item-default", SingleLineVimTextArea).text = "5"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()

    assert isinstance(result, InputArg)
    assert result.default == 5


async def test_input_modal_refuses_save_while_invalid() -> None:
    result: object = "sentinel"
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = InputItemModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#input-item-name", SingleLineVimTextArea).text = "retries"
        modal.query_one("#input-item-type", SingleLineVimTextArea).text = "int"
        modal.query_one(
            "#input-item-default", SingleLineVimTextArea
        ).text = "notanumber"
        await pilot.pause()
        # Invalid default -> save is a no-op, the modal stays open.
        modal.action_save()
        await pilot.pause()
        assert result == "sentinel"
        assert pilot.app.screen is modal

        # Fixing the value lets the save through.
        modal.query_one("#input-item-default", SingleLineVimTextArea).text = "7"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()

    assert isinstance(result, InputArg)
    assert result.default == 7


async def test_input_modal_rejects_duplicate_name() -> None:
    result: object = "sentinel"
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = InputItemModal(used_names=["service"])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#input-item-name", SingleLineVimTextArea).text = "service"
        modal.query_one("#input-item-type", SingleLineVimTextArea).text = "word"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()
        assert result == "sentinel"

        await pilot.press("escape", "escape")
        await pilot.pause()
    assert result is None


# --- interactive: xprompt item modal ---------------------------------------


async def test_xprompt_modal_saves_helper_with_inputs() -> None:
    result: object = None
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = XPromptItemModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#xprompt-item-name", SingleLineVimTextArea).text = "_rules"
        modal.query_one(
            "#xprompt-item-content", VimTextArea
        ).text = "Follow the checklist"
        modal.query_one(
            "#xprompt-item-inputs", SingleLineVimTextArea
        ).text = "service:word"
        modal.query_one(
            "#xprompt-item-description", SingleLineVimTextArea
        ).text = "team rules"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()

    assert isinstance(result, tuple)
    name, xprompt = result
    assert name == "_rules"
    assert isinstance(xprompt, XPrompt)
    assert xprompt.content == "Follow the checklist"
    assert xprompt.description == "team rules"
    assert [a.name for a in xprompt.inputs] == ["service"]


async def test_xprompt_modal_refuses_non_underscore_name() -> None:
    result: object = "sentinel"
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = XPromptItemModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#xprompt-item-name", SingleLineVimTextArea).text = "rules"
        modal.query_one("#xprompt-item-content", VimTextArea).text = "body"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()
        assert result == "sentinel"

        modal.query_one("#xprompt-item-name", SingleLineVimTextArea).text = "_rules"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()

    assert isinstance(result, tuple)
    assert result[0] == "_rules"


async def test_xprompt_modal_refuses_empty_content() -> None:
    result: object = "sentinel"
    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        modal = XPromptItemModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#xprompt-item-name", SingleLineVimTextArea).text = "_rules"
        await pilot.pause()
        modal.action_save()
        await pilot.pause()
        assert result == "sentinel"

        await pilot.press("escape", "escape")
        await pilot.pause()
    assert result is None
