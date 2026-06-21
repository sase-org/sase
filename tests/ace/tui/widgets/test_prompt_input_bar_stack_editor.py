"""Prompt input bar stack tests for editor and xprompt-markdown behavior."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE, PromptFrontmatter

from ._prompt_input_bar_stack_helpers import (
    _PromptBarApp,
    _RecordingPromptBarApp,
    _XPromptMarkdownApp,
)


# --- all-pane editor (prompt editor prefix when stacked) -------------------


async def test_action_open_editor_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # A single-pane bar posts the single-pane editor request, never the
        # all-editor message.
        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []


async def test_action_open_editor_on_stacked_bar_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.focus_item(1)  # the active pane must not narrow the editor scope
        await pilot.pause()

        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # A multi-pane stack posts exactly one all-editor message and never the
        # single-pane editor request; the serialized buffer is the whole stack
        # joined with blank-line-padded ``---`` separators.
        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert (
            bar.xprompt_markdown_for_editor()
            == "first\n\n---\n\nsecond\n\n---\n\nthird"
        )


async def test_action_open_editor_in_feedback_mode_requests_single_pane() -> None:
    app = _RecordingPromptBarApp("draft feedback", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # Feedback bars never stack, so editor access stays single-pane and never
        # reaches the all-editor (multi-agent) surface.
        assert len(app.editor_requests) == 1
        assert app.all_editor_requests == []


async def test_focused_pane_ctrl_g_starts_prefix_and_shadows_global_binding() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert app.focused is bar.active_text_area()

        await pilot.press("ctrl+g")
        await pilot.pause()

        # The focused prompt owns the prefix, so the app-level "edit last VCS
        # xprompt" action never runs and no editor opens until a continuation.
        assert app.editor_requests == []
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0
        assert bar.active_text_area()._insert_g_prefix_pending is True


async def test_focused_normal_mode_ctrl_g_starts_prefix_and_shadows_global_binding() -> (
    None
):
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape", "ctrl+g")
        await pilot.pause()

        # NORMAL-mode ``Ctrl+G`` opens the same prompt-local ``^G`` prefix that
        # INSERT-mode ``Ctrl+G`` does instead of being swallowed: the app-level
        # "edit last VCS xprompt" binding stays shadowed and no editor opens
        # until a continuation key.
        text_area = bar.active_text_area()
        assert text_area._vim_mode == "normal"
        assert text_area._normal_g_prefix_pending is True
        assert app.editor_requests == []
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0

        panel = bar.query_one("#prompt-g-prefix-hints", Static)
        assert not panel.has_class("hidden")
        assert panel.border_title == " ^G "


async def test_normal_ctrl_g_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "ctrl+g", "g")
        await pilot.pause()

        # NORMAL-mode ``Ctrl+G g`` opens the editor just like INSERT-mode
        # ``Ctrl+G g`` and never triggers the app-level binding.
        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_normal_ctrl_g_ctrl_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "ctrl+g", "ctrl+g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_normal_ctrl_g_g_on_stacked_bar_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "ctrl+g", "g")
        await pilot.pause()

        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_ctrl_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "ctrl+g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_g_on_stacked_bar_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "g")
        await pilot.pause()

        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_g_in_feedback_mode_requests_single_pane() -> None:
    app = _RecordingPromptBarApp("draft feedback", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "draft feedback"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


def test_prompt_text_area_no_longer_binds_direct_ctrl_g_editor() -> None:
    actions = {entry[0]: entry[1] for entry in PromptTextArea.BINDINGS}
    assert "ctrl+g" not in actions
    # ``ctrl+shift+g`` is gone too: editor access lives behind the prompt-local
    # insert-mode ``Ctrl+G`` prefix and the programmatic action stays intact.
    assert "ctrl+shift+g" not in actions


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
    """Unlike history load, the all-editor reload lifts a lone body's frontmatter.

    ``load_stack_from_text`` keeps a single prompt with frontmatter verbatim (see
    ``test_single_prompt_with_frontmatter_stays_verbatim``); the all-editor path
    must instead treat the file as xprompt markdown and lift the frontmatter.
    """
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


# --- initial_xprompt_markdown constructor seeding (%edit editor return) -----


async def test_initial_xprompt_markdown_lifts_frontmatter_and_splits() -> None:
    """Constructor seeding with editor-file semantics lifts frontmatter + splits.

    The ``%edit`` editor-return remount path mounts a fresh bar via
    ``initial_xprompt_markdown=...``.  Unlike ``initial_value`` history-load
    semantics - where a single frontmatter prompt stays one verbatim pane (see
    ``test_single_prompt_with_frontmatter_stays_verbatim``) - this lifts leading
    frontmatter onto the stack, splits real ``---`` separators into panes, and
    auto-shows the frontmatter panel on mount.
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
