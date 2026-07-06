"""Tests for the Input Collection Modal (sase-4r.5).

Exercises live validation (required vs optional, each input type, error
guidance), the optional-input reveal toggle, and the confirm/cancel result
contract. The modal returns raw string values keyed by input name; conversion
and substitution are covered separately in ``tests/test_prompt_inputs``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Button, Label

from sase.agent.prompt_inputs import parse_prompt_input_request
from sase.ace.tui.modals.input_collection_modal import InputCollectionModal, _PathField
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _TestApp(App[None]):
    pass


def _request(prompt: str) -> object:
    request = parse_prompt_input_request(prompt)
    assert request is not None
    return request


_REQUIRED_ONLY = "---\ninput:\n  service: word\n  retries: int\n---\n{{ service }}"

_WITH_OPTIONAL = (
    "---\ninput:\n"
    "  service: word\n"
    "  dry_run:\n    type: bool\n    default: false\n"
    "---\n{{ service }}"
)


async def test_confirm_disabled_until_required_filled() -> None:
    modal = InputCollectionModal(_request(_REQUIRED_ONLY), agent_count=2)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        confirm = modal.query_one("#confirm", Button)
        assert confirm.disabled is True
        # Confirm label reflects the agent count.
        assert "2 agents" in str(confirm.label)

        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "billing"
        await pilot.pause()
        assert confirm.disabled is True  # second required input still empty

        modal.query_one("#field-input-1", SingleLineVimTextArea).text = "3"
        await pilot.pause()
        assert confirm.disabled is False


async def test_invalid_value_shows_error_and_blocks_confirm() -> None:
    modal = InputCollectionModal(_request(_REQUIRED_ONLY), agent_count=1)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "billing"
        modal.query_one(
            "#field-input-1", SingleLineVimTextArea
        ).text = "three"  # not an int
        await pilot.pause()

        error = modal.query_one("#field-error-1", Label)
        assert error.display is True
        # Guidance comes from the shared core per-type rule.
        assert "whole number" in str(error.content)
        assert modal.query_one("#confirm", Button).disabled is True


async def test_word_input_rejects_whitespace() -> None:
    modal = InputCollectionModal(_request(_REQUIRED_ONLY), agent_count=1)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "two words"
        await pilot.pause()
        assert modal.query_one("#field-error-0", Label).display is True
        assert modal._field_valid(0) is False


async def test_optional_inputs_hidden_until_revealed() -> None:
    modal = InputCollectionModal(_request(_WITH_OPTIONAL), agent_count=1)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        optional_block = modal.query_one("#field-block-1")
        assert optional_block.display is False
        # Required-only field empty -> confirm still disabled, but the optional
        # field being empty does not block (uses its default).
        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "billing"
        await pilot.pause()
        assert modal.query_one("#confirm", Button).disabled is False

        modal.query_one("#toggle-optional", Button).press()
        await pilot.pause()
        assert optional_block.display is True


async def test_confirm_returns_required_values_and_omits_empty_optional() -> None:
    result: object = "unset"
    modal = InputCollectionModal(_request(_WITH_OPTIONAL), agent_count=1)

    def _on_dismiss(value: object) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=_on_dismiss)
        await pilot.pause()

        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "billing"
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        await pilot.pause()

    # Optional dry_run left empty -> omitted so its default applies downstream.
    assert result == {"service": "billing"}


async def test_confirm_includes_filled_optional_value() -> None:
    result: object = "unset"
    modal = InputCollectionModal(_request(_WITH_OPTIONAL), agent_count=1)

    def _on_dismiss(value: object) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=_on_dismiss)
        await pilot.pause()

        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "billing"
        modal.query_one("#toggle-optional", Button).press()
        await pilot.pause()
        modal.query_one("#field-input-1", SingleLineVimTextArea).text = "true"
        await pilot.pause()
        modal.query_one("#confirm", Button).press()
        await pilot.pause()

    assert result == {"service": "billing", "dry_run": "true"}


async def test_cancel_returns_none() -> None:
    result: object = "unset"
    modal = InputCollectionModal(_request(_REQUIRED_ONLY), agent_count=1)

    def _on_dismiss(value: object) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=_on_dismiss)
        await pilot.pause()
        await pilot.press("escape", "escape")
        await pilot.pause()

    assert result is None


async def test_field_guidance_includes_description_and_rule() -> None:
    prompt = (
        "---\ninput:\n"
        "  retries:\n    type: int\n    description: how many times\n"
        "---\n{{ retries }}"
    )
    modal = InputCollectionModal(_request(prompt), agent_count=1)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        # Description + the shared core per-type rule both appear.
        desc = modal.query_one(".field-desc", Label)
        text = str(desc.content)
        assert "how many times" in text
        assert "whole number" in text


async def test_path_input_uses_ctrl_t_file_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "alpha.txt").write_text("x")
    monkeypatch.chdir(tmp_path)

    prompt = "---\ninput:\n  target: path\n---\n{{ target }}"
    modal = InputCollectionModal(_request(prompt), agent_count=1)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        field = modal.query_one("#field-input-0", _PathField)
        field.text = "alph"
        field.action_complete_path()  # the same engine the prompt panes use
        await pilot.pause()

        assert field.text == "alpha.txt"
