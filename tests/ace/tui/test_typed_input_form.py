"""Widget tests for the shared typed, validated field-collection form."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Label

from sase.ace.tui.widgets.secret_vim_text_area import SecretVimTextArea
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.typed_input_form import (
    TypedFormField,
    TypedInputForm,
    _MultilineInput,
    _PathField,
)
from sase.xprompt.models import UNSET, InputArg, InputChoice, InputType


class _FormApp(App[None]):
    def __init__(
        self,
        fields: Sequence[TypedFormField],
        *,
        optional_toggle: bool = True,
    ) -> None:
        super().__init__()
        self._fields = fields
        self._optional_toggle = optional_toggle

    def compose(self) -> ComposeResult:
        yield TypedInputForm(self._fields, optional_toggle=self._optional_toggle)


def _field(
    name: str,
    type_: InputType,
    *,
    default: object = UNSET,
    choices: tuple[InputChoice, ...] = (),
    repeatable: bool = False,
    secret: bool = False,
) -> TypedFormField:
    return TypedFormField(
        arg=InputArg(
            name=name,
            type=type_,
            default=default,
            choices=choices,
            repeatable=repeatable,
        ),
        secret=secret,
    )


# -- per-type validation ------------------------------------------------------


async def test_word_field_rejects_whitespace() -> None:
    app = _FormApp([_field("service", InputType.WORD)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        editor.text = "two words"
        await pilot.pause()
        assert form.is_valid() is False
        assert app.query_one("#field-error-0", Label).display is True

        editor.text = "billing"
        await pilot.pause()
        assert form.is_valid() is True


@pytest.mark.parametrize(
    ("value", "expected_valid"),
    [("3", True), ("three", False), ("3.5", False)],
)
async def test_int_field_rejects_non_numeric_text(
    value: str, expected_valid: bool
) -> None:
    app = _FormApp([_field("retries", InputType.INT)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        editor.text = value
        await pilot.pause()
        assert form.is_valid() is expected_valid


@pytest.mark.parametrize(
    ("value", "expected_valid"), [("3.5", True), ("3", True), ("abc", False)]
)
async def test_float_field_rejects_non_numeric_text(
    value: str, expected_valid: bool
) -> None:
    app = _FormApp([_field("ratio", InputType.FLOAT)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        editor.text = value
        await pilot.pause()
        assert form.is_valid() is expected_valid


@pytest.mark.parametrize(
    "spelling", ["true", "1", "yes", "on", "false", "0", "no", "off"]
)
async def test_bool_field_accepts_documented_spellings(spelling: str) -> None:
    app = _FormApp([_field("dry_run", InputType.BOOL)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        editor.text = spelling
        await pilot.pause()
        assert form.is_valid() is True


async def test_bool_field_rejects_undocumented_spelling() -> None:
    app = _FormApp([_field("dry_run", InputType.BOOL)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        editor.text = "sure"
        await pilot.pause()
        assert form.is_valid() is False


async def test_path_field_keeps_ctrl_t_file_completion(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    (tmp_path / "alpha.txt").write_text("x")
    monkeypatch.chdir(tmp_path)

    app = _FormApp([_field("target", InputType.PATH)])
    async with app.run_test() as pilot:
        await pilot.pause()
        field = app.query_one("#field-input-0", _PathField)
        field.text = "alph"
        field.action_complete_path()
        await pilot.pause()
        assert field.text == "alpha.txt"


# -- enum -----------------------------------------------------------------


async def test_enum_field_cycles_choices_prefers_label() -> None:
    choices = (
        InputChoice(value="fast", label="Fast mode"),
        InputChoice(value="thorough"),
    )
    app = _FormApp([_field("mode", InputType.ENUM, default="fast", choices=choices)])
    async with app.run_test() as pilot:
        await pilot.pause()
        button = app.query_one("#field-input-0", Button)
        assert str(button.label) == "Fast mode"

        button.press()
        await pilot.pause()
        assert str(button.label) == "thorough"

        button.press()
        await pilot.pause()
        assert str(button.label) == "Fast mode"


async def test_required_enum_with_no_default_starts_unselected_and_blocks_valid() -> (
    None
):
    choices = (InputChoice(value="fast"), InputChoice(value="thorough"))
    app = _FormApp([_field("mode", InputType.ENUM, choices=choices)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        button = app.query_one("#field-input-0", Button)
        assert str(button.label) == "— select —"
        assert form.is_valid() is False

        button.press()
        await pilot.pause()
        assert str(button.label) == "fast"
        assert form.is_valid() is True


async def test_enum_cycle_never_returns_to_sentinel_once_a_choice_is_made() -> None:
    choices = (InputChoice(value="fast"), InputChoice(value="thorough"))
    app = _FormApp([_field("mode", InputType.ENUM, choices=choices)])
    async with app.run_test() as pilot:
        await pilot.pause()
        button = app.query_one("#field-input-0", Button)
        labels: list[str] = []
        for _ in range(4):
            button.press()
            await pilot.pause()
            labels.append(str(button.label))

        assert labels == ["fast", "thorough", "fast", "thorough"]
        assert "— select —" not in labels


# -- repeatable -------------------------------------------------------------


async def test_repeatable_field_splits_newlines_and_converts_each_line() -> None:
    app = _FormApp([_field("tags", InputType.WORD, repeatable=True)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", _MultilineInput)
        editor.text = "alpha\nbeta\n\ngamma"
        await pilot.pause()

        assert form.is_valid() is True
        assert form.typed_values() == {"tags": ["alpha", "beta", "gamma"]}


async def test_text_field_accepts_newline_and_preserves_it() -> None:
    app = _FormApp([_field("notes", InputType.TEXT)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", _MultilineInput)
        editor.focus()
        await pilot.press("a", "enter", "b")
        await pilot.pause()

        assert "\n" in editor.text
        assert form.typed_values() == {"notes": "a\nb"}


async def test_repeatable_line_field_typed_as_two_lines_converts_to_list() -> None:
    app = _FormApp([_field("tags", InputType.LINE, repeatable=True)])
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        editor = app.query_one("#field-input-0", _MultilineInput)
        editor.focus()
        await pilot.press("a", "l", "p", "h", "a", "enter", "b", "e", "t", "a")
        await pilot.pause()

        assert form.typed_values() == {"tags": ["alpha", "beta"]}


async def test_escape_in_multiline_field_enters_normal_mode_and_motion_works() -> None:
    app = _FormApp([_field("notes", InputType.TEXT)])
    async with app.run_test() as pilot:
        await pilot.pause()
        editor = app.query_one("#field-input-0", _MultilineInput)
        editor.text = "hello world"
        editor.cursor_location = (0, 11)
        editor.focus()
        await pilot.press("escape")
        await pilot.pause()
        assert editor._vim_mode == "normal"

        await pilot.press("b")
        await pilot.pause()
        assert editor.cursor_location == (0, 6)


async def test_tab_from_multiline_field_moves_focus() -> None:
    app = _FormApp(
        [
            _field("notes", InputType.TEXT),
            _field("name", InputType.WORD),
        ],
        optional_toggle=False,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        notes = app.query_one("#field-input-0", _MultilineInput)
        name = app.query_one("#field-input-1", SingleLineVimTextArea)
        notes.focus()
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()

        assert name.has_focus
        assert "\t" not in notes.text


# -- secret -------------------------------------------------------------------


async def test_secret_field_renders_masked_input_and_never_leaks_raw_text() -> None:
    app = _FormApp(
        [
            TypedFormField(
                arg=InputArg(name="token", type=InputType.LINE),
                secret=True,
                placeholder="API token",
            )
        ]
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        editor = app.query_one("#field-input-0", SecretVimTextArea)

        empty_rendered = "".join(segment.text for segment in editor.render_line(0))
        assert "API token" in empty_rendered
        assert "•" not in empty_rendered

        editor.text = "hunter2"
        await pilot.pause()
        assert editor.text == "hunter2"
        assert editor.value == "hunter2"
        rendered = "".join(segment.text for segment in editor.render_line(0))
        assert "hunter2" not in rendered
        assert "•" in rendered


# -- optional reveal ----------------------------------------------------------


async def test_optional_reveal_toggles_block_display_without_affecting_validity() -> (
    None
):
    app = _FormApp(
        [
            _field("service", InputType.WORD),
            _field("dry_run", InputType.BOOL, default="false"),
        ]
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        optional_block = app.query_one("#field-block-1")
        assert optional_block.display is False
        assert form.is_valid() is False  # required field 0 is still empty

        required_editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        required_editor.text = "billing"
        await pilot.pause()
        assert form.is_valid() is True  # hidden optional field never blocks

        app.query_one("#toggle-optional", Button).press()
        await pilot.pause()
        assert optional_block.display is True
        assert form.is_valid() is True  # revealed-but-empty optional still valid


# -- invalid focus ------------------------------------------------------------


async def test_focus_first_invalid_prefers_required_visible_field() -> None:
    app = _FormApp(
        [
            _field("retries", InputType.INT, default=0),
            _field("service", InputType.WORD),
        ],
        optional_toggle=False,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        optional_editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        required_editor = app.query_one("#field-input-1", SingleLineVimTextArea)
        optional_editor.text = "many"
        await pilot.pause()

        assert form.focus_first_invalid() is True
        await pilot.pause()
        assert required_editor.has_focus


async def test_focus_first_invalid_falls_back_to_optional_field() -> None:
    app = _FormApp(
        [
            _field("retries", InputType.INT, default=0),
            _field("service", InputType.WORD),
        ],
        optional_toggle=False,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        optional_editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        required_editor = app.query_one("#field-input-1", SingleLineVimTextArea)
        optional_editor.text = "many"
        required_editor.text = "billing"
        await pilot.pause()

        assert form.focus_first_invalid() is True
        await pilot.pause()
        assert optional_editor.has_focus


async def test_focus_first_invalid_returns_false_without_disturbing_valid_focus() -> (
    None
):
    app = _FormApp(
        [
            _field("service", InputType.WORD),
            _field("dry_run", InputType.BOOL, default="false"),
        ],
        optional_toggle=False,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        required_editor = app.query_one("#field-input-0", SingleLineVimTextArea)
        required_editor.text = "billing"
        required_editor.focus()
        await pilot.pause()

        assert form.focus_first_invalid() is False
        await pilot.pause()
        assert required_editor.has_focus


async def test_focus_first_invalid_skips_hidden_fields() -> None:
    app = _FormApp(
        [_field("hidden", InputType.WORD), _field("visible", InputType.WORD)],
        optional_toggle=False,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        form = app.query_one(TypedInputForm)
        visible_editor = app.query_one("#field-input-1", SingleLineVimTextArea)
        form.set_field_visible("hidden", False)
        await pilot.pause()

        assert form.focus_first_invalid() is True
        await pilot.pause()
        assert visible_editor.has_focus
