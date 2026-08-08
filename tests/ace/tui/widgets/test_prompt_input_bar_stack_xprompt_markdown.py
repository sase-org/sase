"""Prompt input bar stack tests for xprompt-markdown editor behavior."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import XPromptBinding
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE, PromptFrontmatter

from ._prompt_input_bar_stack_helpers import _PromptBarApp, _XPromptMarkdownApp


async def test_all_editor_markdown_serializes_canonical_frontmatter() -> None:
    app = _PromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        model = PromptFrontmatter(
            description="do the thing",
            tags=["x", "y"],
            inputs=[InputArg(name="topic", type=InputType.LINE)],
            xprompts={
                "_helper": XPrompt(
                    name="_helper",
                    content="reusable body",
                    source_path=LOCAL_XPROMPT_SOURCE,
                )
            },
            skill=True,
            snippet="#foo",
        )
        bar._stack.set_frontmatter_model(model)

        markdown = bar.xprompt_markdown_for_editor()
        frontmatter = model.serialize()

        # Canonical frontmatter sits above the panes (with a blank-line spacer),
        # which keep launch order separated by blank-line-padded ``---``.
        assert markdown == f"{frontmatter}\n\nalpha\n\n---\n\nbeta"
        for field_name in (
            "description",
            "tags",
            "input",
            "xprompts",
            "skill",
            "snippet",
        ):
            assert field_name in frontmatter


async def test_all_editor_markdown_omits_empty_frontmatter_block() -> None:
    app = _PromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        markdown = bar.xprompt_markdown_for_editor()

        # No properties set -> no leading ``---\n---`` delimiter block.
        assert markdown == "alpha\n\n---\n\nbeta"
        assert not markdown.startswith("---")


async def test_load_stack_from_xprompt_markdown_lifts_frontmatter_and_splits() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_xprompt_markdown("---\ndescription: hi\n---\nuno\n---\ndos")
        await pilot.pause()
        await pilot.pause()

        # Frontmatter is lifted onto the stack; the body splits into panes.
        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["uno", "dos"]
        assert bar._stack.frontmatter == "---\ndescription: hi\n---"
        # The frontmatter panel reflects the lifted frontmatter.
        assert not app.query_one("#frontmatter-panel", FrontmatterPanel).has_class(
            "hidden"
        )


async def test_load_stack_from_xprompt_markdown_lifts_single_body_pane() -> None:
    """The all-editor reload lifts frontmatter from a lone body pane."""
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_xprompt_markdown("---\ndescription: hi\n---\njust body")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "just body"
        assert bar._stack.frontmatter == "---\ndescription: hi\n---"


async def test_prompt_bar_target_api_sets_and_clears_binding(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    binding = XPromptBinding.for_file(source, reference="#review")
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_xprompt_markdown("body\n", binding=binding)
        await pilot.pause()

        assert bar.xprompt_target() == binding
        assert bar.active_text() == "body"
        assert not bar._stack.is_dirty
        assert bar.has_class("xprompt-target")
        assert "#review" in str(bar.border_title)

        bar.clear_xprompt_target()
        await pilot.pause()

        assert bar.xprompt_target() is None
        assert not bar.has_class("xprompt-target")


async def test_preserve_target_reload_keeps_binding_and_dirty_baseline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    binding = XPromptBinding.for_file(source, reference="#review")
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_xprompt_markdown("body\n", binding=binding)
        await pilot.pause()
        assert bar.xprompt_target() == binding
        assert not bar._stack.is_dirty

        bar.load_stack_from_xprompt_markdown(
            "edited\n---\nsecond",
            preserve_target=True,
        )
        await pilot.pause()
        await pilot.pause()

        assert bar.xprompt_target() == binding
        assert bar.all_prompt_texts() == ["edited", "second"]
        assert bar._stack.is_dirty
        assert bar.has_class("dirty")


async def test_load_stack_from_xprompt_markdown_clears_frontmatter_panel() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # A first reload lifts frontmatter and reveals the panel...
        bar.load_stack_from_xprompt_markdown("---\ndescription: hi\n---\nbody")
        await pilot.pause()
        await pilot.pause()
        assert not app.query_one("#frontmatter-panel", FrontmatterPanel).has_class(
            "hidden"
        )

        # ...a later reload with no frontmatter hides the panel again.
        bar.load_stack_from_xprompt_markdown("plain body\n---\nsecond")
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.frontmatter == ""
        assert app.query_one("#frontmatter-panel", FrontmatterPanel).has_class("hidden")


async def test_initial_xprompt_markdown_lifts_frontmatter_and_splits() -> None:
    """Constructor seeding with editor-file semantics lifts frontmatter + splits.

    The ` @`-review-marker editor-return remount path mounts a fresh bar via
    ``initial_xprompt_markdown=...``.  This lifts leading frontmatter onto the
    stack, splits real ``---`` separators into panes, and auto-shows the
    frontmatter panel on mount.
    """
    markdown = (
        "---\n"
        "description: Review auth and API separately\n"
        "xprompts:\n"
        "  _shared: Use the same style guide.\n"
        "---\n"
        "Review auth.\n"
        "---\n"
        "Review API."
    )
    app = _XPromptMarkdownApp(markdown)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["Review auth.", "Review API."]
        assert bar._stack.frontmatter == (
            "---\n"
            "description: Review auth and API separately\n"
            "xprompts:\n"
            "  _shared: Use the same style guide.\n"
            "---"
        )
        # The frontmatter panel auto-shows on mount, reflecting the lifted props.
        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        assert not panel.has_class("hidden")
        model = bar._stack.frontmatter_model
        assert model.description == "Review auth and API separately"
        assert "_shared" in model.xprompts


async def test_initial_xprompt_markdown_protects_fenced_separator() -> None:
    initial = "before\n```\n---\nstill code\n```\nafter"
    app = _XPromptMarkdownApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # A ``---`` inside a fenced block is not a separator: one verbatim pane.
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == initial
        assert bar._stack.frontmatter == ""
