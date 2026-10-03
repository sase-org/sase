"""Tests for Jinja2 prompt input support."""

from __future__ import annotations

import pytest
from textual.css.query import NoMatches
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_completion import (
    PromptCompletionSettings,
    build_prompt_soft_completion,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    XPromptInputHint,
)
from sase.macro.models import InputArg, InputType
from sase.macro.prompt_frontmatter import PromptFrontmatter

from ._completion_helpers import CompletionTestApp


async def _compute_jinja_now(ta: PromptTextArea) -> None:
    ta._jinja_diagnostics_generation += 1
    generation = ta._jinja_diagnostics_generation
    ta._fire_jinja_diagnostics_timer(
        generation,
        ta.text,
        ta._absolute_offset(ta.cursor_location),
    )
    task = ta._jinja_diagnostics_task
    if task is not None:
        await task


async def test_jinja_highlight_overlay_adds_spans() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Hello {{ root | tojson }}")
        ta.cursor_location = (0, len(ta.text))
        ta._build_highlight_map()

    names = [name for row in ta._highlights.values() for *_range, name in row]
    assert "jinja.delimiter" in names
    assert "jinja.variable" in names
    assert "jinja.filter" in names


async def test_jinja_valid_chip_and_invalid_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)

        ta.load_text("Hello {{ root }}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)
        assert "jinja ✓" in str(bar.border_title)
        assert panel.has_class("hidden")

        ta.load_text("Hello {{ name }")
        ta.cursor_location = (0, len(ta.text))
        ta._on_prompt_completion_context_changed()
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ! L1" in str(bar.border_title)
    assert panel.border_title == "jinja diagnostics"
    assert "unexpected" in panel.render().plain.lower()
    assert panel.has_class("jinja-error")


async def test_jinja_unknown_variable_warning() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)

        ta.load_text("Hello {{ missing }}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ! var" in str(bar.border_title)
    assert panel.border_title == "jinja diagnostics"
    assert "missing" in panel.render().plain
    assert panel.has_class("jinja-warning")
    assert ta._jinja_unknown_spans


async def test_jinja_diagnostics_knows_stack_frontmatter_inputs() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )

        ta.load_text("{{ topic }} {{ root }}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ✓" in str(bar.border_title)
    assert panel.has_class("hidden")
    assert ta._jinja_unknown_spans == ()


async def test_jinja_diagnostics_patch_name_known_without_inputs() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)

        ta.load_text("{{ patch_name }} {{ wait_chats }} {{ n }}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ✓" in str(bar.border_title)
    assert panel.has_class("hidden")
    assert ta._jinja_unknown_spans == ()


async def test_jinja_diagnostics_run_names_unavailable_in_input_declaring_prompt() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )

        ta.load_text("{{ topic }} {{ patch_name }}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ! var" in str(bar.border_title)
    assert panel.border_title == "jinja diagnostics"
    plain = panel.render().plain
    assert "patch_name" in plain
    assert "unknown variable" not in plain
    assert ta._jinja_diagnostics.unknown_variables == ()
    assert [item.name for item in ta._jinja_diagnostics.unavailable_variables] == [
        "patch_name"
    ]
    assert ta._jinja_unknown_spans


async def test_jinja_diagnostics_still_flags_unknown_with_known_context() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )

        ta.load_text("{{ topic }} {{ wait_chats }} {{ definitely_unknown }}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ! var" in str(bar.border_title)
    assert panel.border_title == "jinja diagnostics"
    assert "definitely_unknown" in panel.render().plain
    assert ta._jinja_diagnostics.unknown_variables == ("definitely_unknown",)
    assert ta._jinja_unknown_spans


async def test_jinja_diagnostics_knows_inline_frontmatter_inputs() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)

        ta.load_text("---\ninput:\n  topic: line\n---\n{{ topic }} {{ root }}")
        ta.cursor_location = (4, len("{{ topic }} {{ root }}"))
        await pilot.pause()
        await _compute_jinja_now(ta)

    assert "jinja ✓" in str(bar.border_title)
    assert panel.has_class("hidden")
    assert ta._jinja_unknown_spans == ()


async def test_completion_panel_entrypoints_noop_when_panel_pruned() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)
        await panel.remove()

        with pytest.raises(NoMatches):
            bar.query_one("#prompt-completion", Static)

        ta.load_text("{{}}")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        await _compute_jinja_now(ta)

        candidate = CompletionCandidate(
            display="alpha.txt",
            insertion="alpha.txt",
            is_dir=False,
            name="alpha.txt",
        )
        bar.show_file_completions("a", [candidate], selected_index=0)
        bar.hide_file_completions()

        input_hint = XPromptInputHint(
            name="path",
            type="path",
            required=True,
            default_display=None,
            position=0,
        )
        entry = XPromptAssistEntry(
            name="review",
            insertion="#review",
            reference_prefix="#",
            kind="xprompt",
            input_signature=None,
            inputs=(input_hint,),
            content_preview=None,
        )
        bar.show_xprompt_arg_hint(
            ActiveXPromptArgHint(
                entry=entry,
                reference_start=0,
                reference_end=len("#review"),
                reference_text="#review",
            )
        )

        assert bar._completion_visible is False


async def test_jinja_auto_pairing() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("{", "{")
        assert ta.text == "{{  }}"
        assert ta.cursor_location == (0, 3)

        ta.load_text("")
        ta.cursor_location = (0, 0)
        await pilot.press("{", "%")
        assert ta.text == "{%  %}"
        assert ta.cursor_location == (0, 3)


async def test_jinja_ctrl_t_completion() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Hello {{ roo }}")
        ta.cursor_location = (0, len("Hello {{ roo"))

        await pilot.press("ctrl+t")

    assert ta.text == "Hello {{ root }}"


def test_jinja_soft_completion() -> None:

    suggestion = build_prompt_soft_completion(
        text="Hello {{ ro }}",
        cursor_offset=len("Hello {{ ro"),
        settings=PromptCompletionSettings(),
        macro_entries=[],
    )

    assert suggestion is not None
    assert suggestion.completion_kind == "jinja"
    assert suggestion.display == "root"


def test_jinja_soft_completion_includes_runtime_builtins() -> None:

    suggestion = build_prompt_soft_completion(
        text="Hello {{ wait_ }}",
        cursor_offset=len("Hello {{ wait_"),
        settings=PromptCompletionSettings(),
        macro_entries=[],
    )

    assert suggestion is not None
    assert suggestion.completion_kind == "jinja"
    assert suggestion.display == "wait_chats"


def test_jinja_soft_completion_includes_wait_namespace_members() -> None:

    suggestion = build_prompt_soft_completion(
        text="Hello {{ wait.art }}",
        cursor_offset=len("Hello {{ wait.art"),
        settings=PromptCompletionSettings(),
        macro_entries=[],
    )

    assert suggestion is not None
    assert suggestion.completion_kind == "jinja"
    assert suggestion.display == "artifacts"


def test_jinja_soft_completion_never_falls_through_to_directive() -> None:
    for text in ("{{ foo %mo", '{% set x = "%mod'):
        suggestion = build_prompt_soft_completion(
            text=text,
            cursor_offset=len(text),
            settings=PromptCompletionSettings(),
            macro_entries=[],
        )

        assert suggestion is None, text
