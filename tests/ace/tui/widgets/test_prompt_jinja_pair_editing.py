"""Tests for paired deletion of Jinja variable delimiters in the prompt input."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets._jinja_pair_editing import (
    plan_jinja_delete_left,
    plan_jinja_delete_right,
)
from sase.ace.tui.widgets._paired_text_editing import TextEdit
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class JinjaPairTestApp(App[None]):
    """Minimal app that hosts a PromptTextArea without frontmatter dependencies."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield PromptInputBar(mode="feedback")


# --------------------------------------------------------------------------- #
# Delimiter deletion: first opening ``{`` removes the last closing ``}``       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected_text"),
    [("{{}}", "{}"), ("{{  }}", "{  }"), ("{{ name }}", "{ name }")],
)
def test_delete_left_first_brace_removes_last_brace(
    text: str, expected_text: str
) -> None:
    # Backspace with the cursor just after the first ``{`` (offset 1).
    plan = plan_jinja_delete_left(text, 1)
    assert plan is not None
    assert _apply(text, plan) == expected_text
    assert plan.cursor == 0


@pytest.mark.parametrize(
    ("text", "expected_text"),
    [("{{}}", "{}"), ("{{  }}", "{  }"), ("{{ name }}", "{ name }")],
)
def test_delete_right_first_brace_removes_last_brace(
    text: str, expected_text: str
) -> None:
    # Forward Delete with the cursor before the first ``{`` (offset 0).
    plan = plan_jinja_delete_right(text, 0)
    assert plan is not None
    assert _apply(text, plan) == expected_text
    assert plan.cursor == 0


# --------------------------------------------------------------------------- #
# Delimiter deletion: second opening ``{`` removes the first closing ``}``     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected_text"),
    [("{{}}", "{}"), ("{{  }}", "{  }"), ("{{ name }}", "{ name }")],
)
def test_delete_left_second_brace_removes_first_brace(
    text: str, expected_text: str
) -> None:
    # Backspace with the cursor just after the second ``{`` (offset 2).
    plan = plan_jinja_delete_left(text, 2)
    assert plan is not None
    assert _apply(text, plan) == expected_text
    assert plan.cursor == 1


@pytest.mark.parametrize(
    ("text", "expected_text"),
    [("{{}}", "{}"), ("{{  }}", "{  }"), ("{{ name }}", "{ name }")],
)
def test_delete_right_second_brace_removes_first_brace(
    text: str, expected_text: str
) -> None:
    # Forward Delete with the cursor before the second ``{`` (offset 1).
    plan = plan_jinja_delete_right(text, 1)
    assert plan is not None
    assert _apply(text, plan) == expected_text
    assert plan.cursor == 1


# --------------------------------------------------------------------------- #
# Boundary padding deletion: deleting one boundary space removes the other     #
# --------------------------------------------------------------------------- #


def test_delete_left_padding_collapses_generated_empty_pair() -> None:
    # ``{{ | }}`` -- Backspace the left boundary space at offset 2.
    plan = plan_jinja_delete_left("{{  }}", 3)
    assert plan is not None
    assert plan == TextEdit(start=2, end=4, text="", cursor=2)
    assert _apply("{{  }}", plan) == "{{}}"


def test_delete_right_padding_collapses_generated_empty_pair() -> None:
    # Forward Delete the left boundary space at offset 2.
    plan = plan_jinja_delete_right("{{  }}", 2)
    assert plan is not None
    assert plan == TextEdit(start=2, end=4, text="", cursor=2)
    assert _apply("{{  }}", plan) == "{{}}"


def test_delete_left_padding_strips_spacing_around_name() -> None:
    # ``{{ |name }}`` -- Backspace the left boundary space at offset 2.
    plan = plan_jinja_delete_left("{{ name }}", 3)
    assert plan is not None
    assert _apply("{{ name }}", plan) == "{{name}}"
    assert plan.cursor == 2


def test_delete_right_boundary_space_strips_spacing_around_name() -> None:
    # ``{{ name| }}`` -- Backspace the right boundary space at offset 8.
    plan = plan_jinja_delete_left("{{ name }}", 8)
    assert plan is not None
    assert _apply("{{ name }}", plan) == "{{name}}"


def test_forward_delete_right_boundary_space_strips_spacing() -> None:
    # ``{{ name| }}`` -- forward Delete the right boundary space at offset 7.
    plan = plan_jinja_delete_right("{{ name }}", 7)
    assert plan is not None
    assert _apply("{{ name }}", plan) == "{{name}}"


# --------------------------------------------------------------------------- #
# Non-matching cases return ``None``                                          #
# --------------------------------------------------------------------------- #


def test_interior_space_is_not_paired() -> None:
    # The space between ``a`` and ``b`` is interior, not a boundary space.
    assert plan_jinja_delete_left("{{ a b }}", 5) is None
    assert plan_jinja_delete_right("{{ a b }}", 4) is None


def test_single_space_tag_is_not_paired() -> None:
    # ``{{ }}`` has only one space; there is no second boundary space to pair.
    assert plan_jinja_delete_left("{{ }}", 3) is None
    assert plan_jinja_delete_right("{{ }}", 2) is None


def test_malformed_unclosed_tag_returns_none() -> None:
    # A missing second ``}`` means there is no ``}}`` mirror.
    assert plan_jinja_delete_left("{{ name }", 1) is None
    assert plan_jinja_delete_left("{{ name }", 2) is None
    assert plan_jinja_delete_right("{{ name }", 0) is None


def test_lone_open_brace_returns_none() -> None:
    assert plan_jinja_delete_left("{", 1) is None
    assert plan_jinja_delete_right("{", 0) is None


def test_single_brace_tag_is_not_jinja() -> None:
    # ``{ name }`` is not a Jinja variable delimiter.
    assert plan_jinja_delete_left("{ name }", 1) is None
    assert plan_jinja_delete_right("{ name }", 0) is None
    # Its interior spaces must not pair either.
    assert plan_jinja_delete_left("{ name }", 2) is None


def test_out_of_range_offsets_return_none() -> None:
    assert plan_jinja_delete_left("{{}}", 0) is None
    assert plan_jinja_delete_right("{{}}", 4) is None


def test_non_delimiter_character_returns_none() -> None:
    # The cursor sits on a letter, not a brace or boundary space.
    assert plan_jinja_delete_left("{{ name }}", 4) is None
    assert plan_jinja_delete_right("{{ name }}", 3) is None


# --------------------------------------------------------------------------- #
# Multiline absolute-offset behavior                                          #
# --------------------------------------------------------------------------- #


def test_delete_second_brace_multiline_offset() -> None:
    text = "x\n{{ name }}"
    # ``{{`` opens at offset 2; Backspace the second ``{`` at offset 4.
    plan = plan_jinja_delete_left(text, 4)
    assert plan is not None
    assert _apply(text, plan) == "x\n{ name }"
    assert plan.cursor == 3


def test_delete_padding_multiline_offset() -> None:
    text = "x\n{{  }}"
    # Backspace the left boundary space at offset 4.
    plan = plan_jinja_delete_left(text, 5)
    assert plan is not None
    assert _apply(text, plan) == "x\n{{}}"
    assert plan.cursor == 4


# --------------------------------------------------------------------------- #
# Textual integration                                                         #
# --------------------------------------------------------------------------- #


async def test_backspace_sequence_unwinds_generated_variable() -> None:
    app = JinjaPairTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("{", "{")
        assert ta.text == "{{  }}"
        assert ta.cursor_location == (0, 3)

        await pilot.press("backspace")
        assert ta.text == "{{}}"
        assert ta.cursor_location == (0, 2)

        await pilot.press("backspace")
        assert ta.text == "{}"
        assert ta.cursor_location == (0, 1)

        await pilot.press("backspace")
        assert ta.text == ""


async def test_backspace_second_brace_removes_first_close_brace() -> None:
    app = JinjaPairTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ name }}")
        ta.cursor_location = (0, 2)
        await pilot.press("backspace")
        assert ta.text == "{ name }"
        assert ta.cursor_location == (0, 1)


async def test_backspace_left_padding_strips_both_boundary_spaces() -> None:
    app = JinjaPairTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ name }}")
        ta.cursor_location = (0, 3)
        await pilot.press("backspace")
        assert ta.text == "{{name}}"
        assert ta.cursor_location == (0, 2)


async def test_forward_delete_first_brace_removes_last_brace() -> None:
    app = JinjaPairTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ name }}")
        ta.cursor_location = (0, 0)
        await pilot.press("delete")
        assert ta.text == "{ name }"
        assert ta.cursor_location == (0, 0)


async def test_forward_delete_padding_strips_both_boundary_spaces() -> None:
    app = JinjaPairTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{  }}")
        ta.cursor_location = (0, 2)
        await pilot.press("delete")
        assert ta.text == "{{}}"
        assert ta.cursor_location == (0, 2)


def _apply(text: str, plan: TextEdit) -> str:
    """Return ``text`` with ``plan`` applied, mirroring the widget's edit."""
    return text[: plan.start] + plan.text + text[plan.end :]
