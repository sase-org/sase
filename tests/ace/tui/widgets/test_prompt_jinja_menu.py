"""Pilot tests for the engine-backed Jinja2 completion menu."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_completion_panel_kinds import (
    CompletionPanelKinds,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    completion_panel_title,
    jinja_completion_subtitle,
)
from sase.ace.tui.widgets.jinja_completion import (
    JinjaCompletionMetadata,
    build_jinja_completion_result,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.macro.jinja_assist import JinjaScope
from sase.macro.models import InputArg, InputType
from sase.macro.prompt_frontmatter import PromptFrontmatter

from ._completion_helpers import CompletionTestApp
from ._prompt_stack_helpers import mini_macro_target

PROMPT_SCOPE = JinjaScope(kind="prompt", frontmatter=None)


def _names(text: str, scope: JinjaScope = PROMPT_SCOPE) -> list[str]:
    result = build_jinja_completion_result(text, len(text), scope)
    assert result is not None
    return [candidate.name for candidate in result.candidates]


def _menu_names(text: str, scope: JinjaScope = PROMPT_SCOPE) -> list[str]:
    return _names(text, scope)


async def test_stack_frontmatter_inputs_listed_first() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )
        scope = bar.jinja_scope_for_text_area(ta)

        assert scope.kind == "prompt"
        assert scope.frontmatter is not None
        names = _menu_names("{{ ", scope)

    assert names[0] == "topic"


async def test_mini_pane_offers_own_inputs_plus_args() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        bar._stack.selected_item.mini_macro_target = mini_macro_target(
            name="review",
            frontmatter="input:\n  topic: line\n",
        )
        scope = bar.jinja_scope_for_text_area(ta)

        assert scope.kind == "macro"
        names = _menu_names("{{ ", scope)

    assert "topic" in names
    assert "_args" in names
    assert bar.jinja_scope_label_for_text_area(ta) == "#review"


async def test_scope_accessor_modes() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        scope = bar.jinja_scope_for_text_area(ta)
        assert scope == JinjaScope(kind="prompt", frontmatter=None)

        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )
        bound = bar.jinja_scope_for_text_area(ta)
        assert bound.kind == "prompt"
        assert bound.frontmatter is not None


async def test_conditional_n_renders_dim_with_hint() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        panel = bar.query_one("#prompt-completion", Static)

        ta.load_text("{{ n }}")
        ta.cursor_location = (0, len("{{ n"))
        await pilot.press("ctrl+t")

        assert ta._completion_kind == "jinja"
        index = next(
            i
            for i, candidate in enumerate(ta._file_completion_candidates)
            if candidate.name == "n"
        )
        metadata = ta._file_completion_candidates[index].metadata
        assert isinstance(metadata, JinjaCompletionMetadata)
        assert metadata.availability == "conditional"
        assert metadata.hint is not None and "%repeat" in metadata.hint

        subtitle = jinja_completion_subtitle(ta._file_completion_candidates, index, 120)
        assert "⚠" in subtitle.plain
        assert "%repeat" in subtitle.plain

        plain = panel.render().plain
        assert "n" in plain
        assert "%repeat" in str(panel.border_subtitle)


async def test_input_declaring_prompt_hides_patch_name() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )
        scope = bar.jinja_scope_for_text_area(ta)

        names = _menu_names("{{ ", scope)

    assert "topic" in names
    assert "patch_name" not in names


async def test_menu_rows_match_engine_order() -> None:
    from sase.macro import jinja_assist

    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.LINE)])
        )
        ta.load_text("{{ ")
        ta.cursor_location = (0, len("{{ "))
        scope = bar.jinja_scope_for_text_area(ta)

        await pilot.press("ctrl+t")

        assert ta._completion_kind == "jinja"
        menu_names = [candidate.name for candidate in ta._file_completion_candidates]
        engine = jinja_assist.jinja_completion(ta.text, len(ta.text), scope)
        assert engine is not None
        engine_names = [item.name for item in engine.items]
        assert menu_names == engine_names


async def test_filter_slot_gives_filters() -> None:
    result = build_jinja_completion_result("{{ x | ", len("{{ x | "), PROMPT_SCOPE)

    assert result is not None
    assert result.slot == "filter"
    assert result.candidates
    assert all(
        isinstance(candidate.metadata, JinjaCompletionMetadata)
        and candidate.metadata.kind == "filter"
        for candidate in result.candidates
    )
    kinds = CompletionPanelKinds.classify("jinja", result.candidates)
    assert completion_panel_title(kinds, result.prefix, result.candidates, "") == (
        "| filters"
    )


async def test_member_slot_gives_members() -> None:
    result = build_jinja_completion_result("{{ wait.", len("{{ wait."), PROMPT_SCOPE)

    assert result is not None
    assert result.slot == "member"
    assert [candidate.name for candidate in result.candidates] == [
        "chats",
        "artifacts",
    ]
    kinds = CompletionPanelKinds.classify("jinja", result.candidates)
    assert completion_panel_title(kinds, result.prefix, result.candidates, "") == (
        "wait. members"
    )


async def test_statement_closer_first_inside_for() -> None:
    text = "{% for x in y %}{% "
    result = build_jinja_completion_result(text, len(text), PROMPT_SCOPE)

    assert result is not None
    assert result.slot == "statement"
    assert result.candidates[0].name == "endfor"
    kinds = CompletionPanelKinds.classify("jinja", result.candidates)
    assert completion_panel_title(kinds, result.prefix, result.candidates, "") == (
        "{% statements"
    )


async def test_scope_label_appears_in_title() -> None:
    result = build_jinja_completion_result(
        "{{ ", len("{{ "), PROMPT_SCOPE, scope_label="#research"
    )

    assert result is not None
    kinds = CompletionPanelKinds.classify("jinja", result.candidates)
    assert completion_panel_title(kinds, result.prefix, result.candidates, "") == (
        "{{ variables · #research"
    )


async def test_test_slot_title() -> None:
    result = build_jinja_completion_result("{{ x is ", len("{{ x is "), PROMPT_SCOPE)

    assert result is not None
    assert result.slot == "test"
    kinds = CompletionPanelKinds.classify("jinja", result.candidates)
    assert completion_panel_title(kinds, result.prefix, result.candidates, "") == (
        "is tests"
    )


async def test_legacy_subtitle_names_canonical() -> None:
    result = build_jinja_completion_result("{{ cl_", len("{{ cl_"), PROMPT_SCOPE)

    assert result is not None
    index = next(
        i
        for i, candidate in enumerate(result.candidates)
        if candidate.name == "cl_name"
    )
    subtitle = jinja_completion_subtitle(result.candidates, index, 120)

    assert "legacy → patch_name" in subtitle.plain


async def test_in_tag_precedence_over_placeholder_and_at() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        # Outside a tag the placeholder surface owns this cursor shape.
        ta.load_text("Use <alpha> <apricot> then <a")
        ta.cursor_location = (0, len("Use <alpha> <apricot> then <a"))
        await pilot.press("ctrl+t")
        assert ta._completion_kind == "placeholder"

        # Inside a tag the engine claims the same cursor shape.
        ta.load_text("{{ <alpha> <apricot> then <a")
        ta.cursor_location = (0, len("{{ <alpha> <apricot> then <a"))
        await pilot.press("ctrl+t")
        assert ta._completion_kind == "jinja"

        # An ``@`` trigger inside a tag never reaches artifact completion:
        # the engine claims the cursor with an empty slot and no menu.
        before = "{{ @foo"
        ta.load_text(before)
        ta.cursor_location = (0, len(before))
        await pilot.press("ctrl+t")
        assert ta.text == before
        assert ta._file_completion_active is False

        # A comparison ``<`` inside a tag is not a placeholder either.
        before = "{{ a < b"
        ta.load_text(before)
        ta.cursor_location = (0, len(before))
        await pilot.press("ctrl+t")
        assert ta.text == before
        assert ta._file_completion_active is False


async def test_fenced_block_opens_no_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "```\n{{ ro\n```\n"
        ta.load_text(text)
        ta.cursor_location = (1, len("{{ ro"))

        result = build_jinja_completion_result(
            ta.text, ta._absolute_offset(ta.cursor_location), PROMPT_SCOPE
        )

    assert result is None


async def test_accept_replaces_identifier_with_bare_name() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        ta.load_text("Hello {{ roo }}")
        ta.cursor_location = (0, len("Hello {{ roo"))
        await pilot.press("ctrl+t")

    assert ta.text == "Hello {{ root }}"


async def test_member_accept_inserts_bare_member_name() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        ta.load_text("{{ wait.chats }}")
        ta.cursor_location = (0, len("{{ wait.chats"))
        await pilot.press("ctrl+t")
        await pilot.press("enter")

    assert ta.text == "{{ wait.chats }}"
