"""Prompt input bar stack tests for staged xprompt frontmatter inputs."""

from __future__ import annotations

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

from ._prompt_input_bar_stack_helpers import _PromptBarApp


async def test_merge_frontmatter_inputs_shows_panel_without_stealing_focus() -> None:
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        text_area.focus()
        await pilot.pause()

        topic = InputArg(name="topic", type=InputType.LINE)
        bar.merge_frontmatter_inputs([topic])
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert not panel.has_class("hidden")
        assert panel.model.inputs == [topic]
        assert bar._stack.frontmatter == "---\ninput:\n  topic: line\n---"
        assert app.focused is text_area


def test_merge_frontmatter_inputs_keeps_existing_declaration_on_collision() -> None:
    bar = PromptInputBar()
    existing = InputArg(
        name="topic",
        type=InputType.WORD,
        description="existing prompt declaration",
    )
    incoming = InputArg(name="topic", type=InputType.INT)
    target = InputArg(name="target", type=InputType.PATH)
    frontmatter = PromptFrontmatter(inputs=[existing])
    bar._stack.set_frontmatter_model(frontmatter)

    bar.merge_frontmatter_inputs([incoming, target])

    model = PromptFrontmatter.parse(bar._stack.frontmatter)
    assert model.inputs == [existing, target]


def test_merge_frontmatter_inputs_leaves_invalid_frontmatter_unchanged() -> None:
    bar = PromptInputBar()
    original = "---\nxprompts:\n  rules: missing underscore\n---"
    bar._stack.frontmatter = original

    bar.merge_frontmatter_inputs([InputArg(name="topic", type=InputType.LINE)])

    assert bar._stack.frontmatter == original


def test_merge_frontmatter_inputs_reports_only_names_actually_added() -> None:
    bar = PromptInputBar()
    existing = InputArg(name="topic", type=InputType.WORD)
    bar._stack.set_frontmatter_model(PromptFrontmatter(inputs=[existing]))

    # `topic` collides with the user's declaration and is skipped; only the
    # genuinely new `target` is reported as added (and thus owned).
    added = bar.merge_frontmatter_inputs(
        [InputArg(name="topic", type=InputType.INT), InputArg(name="target")]
    )

    assert added == ["target"]


def _apply_inline_expansion(
    bar: PromptInputBar,
    text_area: PromptTextArea,
    trigger_range: tuple[tuple[int, int], tuple[int, int]],
    body: str,
    inputs: list[InputArg],
) -> tuple[str, str]:
    """Mirror the ``Ctrl+I`` callback on *bar*: splice, stage, register.

    Returns ``(before_text, after_text)`` so a test can replay the exact undo /
    redo body-text transition through the bar's transaction handlers.
    """
    before_text = text_area.text
    assert bar.expand_xprompt_at_target(
        text_area, text_area.id or "", trigger_range, body
    )
    after_text = text_area.text
    added = bar.merge_frontmatter_inputs(inputs)
    bar.register_inline_expansion(
        text_area, text_area.id or "", before_text, inputs, added
    )
    return before_text, after_text


async def test_undo_unstages_input_and_clears_frontmatter() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        assert PromptFrontmatter.parse(bar._stack.frontmatter).get_input("topic")

        bar.handle_text_area_undo(pane, after, before)

        # The lone auto-staged input is removed, clearing the frontmatter
        # entirely so the panel can hide.
        assert bar._stack.frontmatter == ""
        assert app.query_one(FrontmatterPanel).has_class("hidden")


async def test_undo_removes_multiple_staged_inputs_together() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }} {{ depth }}",
            [
                InputArg(name="topic", type=InputType.LINE),
                InputArg(name="depth", type=InputType.INT),
            ],
        )
        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.get_input("topic") and model.get_input("depth")

        bar.handle_text_area_undo(pane, after, before)

        assert bar._stack.frontmatter == ""


async def test_undo_keeps_unrelated_properties_and_panel_visible() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        # A user-authored property exists before the expansion.
        bar._stack.set_frontmatter_model(PromptFrontmatter(description="hi"))
        bar.refresh_frontmatter_panel_from_stack()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )

        bar.handle_text_area_undo(pane, after, before)

        # Only the expansion-added input is removed; the user's `description`
        # survives and the panel stays visible.
        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.description == "hi"
        assert model.get_input("topic") is None
        assert not app.query_one(FrontmatterPanel).has_class("hidden")


async def test_undo_preserves_preexisting_input_declaration() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        existing = InputArg(
            name="topic", type=InputType.WORD, description="user authored"
        )
        bar._stack.set_frontmatter_model(PromptFrontmatter(inputs=[existing]))
        bar.refresh_frontmatter_panel_from_stack()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        # The collision left the user's WORD declaration untouched.
        assert PromptFrontmatter.parse(bar._stack.frontmatter).inputs == [existing]

        bar.handle_text_area_undo(pane, after, before)

        # Undo must not remove a declaration the expansion never owned.
        assert PromptFrontmatter.parse(bar._stack.frontmatter).inputs == [existing]


async def test_undo_two_expansions_one_pane_is_lifo() -> None:
    app = _PromptBarApp("#\n#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        pane.load_text("#\n#")

        before1, after1 = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        before2, after2 = _apply_inline_expansion(
            bar,
            pane,
            ((1, 0), (1, 1)),
            "{{ subject }}",
            [InputArg(name="subject", type=InputType.LINE)],
        )
        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.get_input("topic") and model.get_input("subject")

        # First undo (the most recent expansion) removes only `subject`.
        bar.handle_text_area_undo(pane, after2, before2)
        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.get_input("topic") is not None
        assert model.get_input("subject") is None

        # Next undo removes the first expansion's `topic`.
        bar.handle_text_area_undo(pane, after1, before1)
        assert bar._stack.frontmatter == ""


async def test_undo_shared_input_kept_until_last_dependent_undone() -> None:
    app = _PromptBarApp("#\n---\n#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        upper, lower = list(bar.query(PromptTextArea))

        # Expansion A (upper pane) auto-stages `topic`.
        before_a, after_a = _apply_inline_expansion(
            bar,
            upper,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        # Expansion B (lower pane) reuses `topic`; the collision adds nothing but
        # its body still depends on the shared declaration.
        before_b, after_b = _apply_inline_expansion(
            bar,
            lower,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        assert PromptFrontmatter.parse(bar._stack.frontmatter).get_input("topic")

        # Undoing the original owner does not strip `topic` while B still needs it.
        bar.handle_text_area_undo(upper, after_a, before_a)
        assert PromptFrontmatter.parse(bar._stack.frontmatter).get_input("topic")

        # Undoing the last dependent finally removes the shared input.
        bar.handle_text_area_undo(lower, after_b, before_b)
        assert (
            PromptFrontmatter.parse(bar._stack.frontmatter).get_input("topic") is None
        )


async def test_redo_restages_input_after_undo() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        bar.handle_text_area_undo(pane, after, before)
        assert bar._stack.frontmatter == ""

        bar.handle_text_area_redo(pane, before, after)

        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.get_input("topic") is not None


async def test_redo_does_not_overwrite_user_authored_declaration() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        bar.handle_text_area_undo(pane, after, before)
        # The user authors their own `topic` (a different type) after the undo.
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(inputs=[InputArg(name="topic", type=InputType.WORD)])
        )

        bar.handle_text_area_redo(pane, before, after)

        # Redo restores the body but must not clobber the user's declaration.
        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        topic = model.get_input("topic")
        assert topic is not None and topic.type == InputType.WORD


async def test_undo_leaves_invalid_frontmatter_unchanged() -> None:
    app = _PromptBarApp("#")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        pane = bar.active_text_area()
        pane.load_text("#")
        pane.cursor_location = (0, 1)

        before, after = _apply_inline_expansion(
            bar,
            pane,
            ((0, 0), (0, 1)),
            "{{ topic }}",
            [InputArg(name="topic", type=InputType.LINE)],
        )
        # The frontmatter is now mid-edit / invalid (a non-underscore helper).
        invalid = "---\nxprompts:\n  rules: missing underscore\n---"
        bar._stack.frontmatter = invalid

        bar.handle_text_area_undo(pane, after, before)

        # The unstage path refuses to rewrite frontmatter it cannot parse.
        assert bar._stack.frontmatter == invalid
