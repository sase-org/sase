"""Widget-level tests for the multi-agent prompt stack rendering (Phase 2).

Covers the Phase 2 deliverable of ``PromptInputBar``: initial text containing
``---`` separators renders as stacked panes, single prompts (including ones with
YAML frontmatter) stay a single verbatim pane, the stack-aware helper APIs read
the live panes, and the stack height stays within the terminal with the active
pane growing while inactive panes compact.
"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE, PromptFrontmatter


class _PromptBarApp(App[None]):
    """Minimal app that hosts a single prompt input bar."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )


def _height(value: Any) -> int:
    """Return a numeric height from a Textual style value."""
    return int(getattr(value, "value", value))


def _pane_heights(app: _PromptBarApp, bar: PromptInputBar) -> list[int]:
    """Return the content height of each pane, top-to-bottom."""
    heights: list[int] = []
    for item in bar._stack.items:
        pane = app.query_one(f"#{bar._pane_id(item)}", PromptTextArea)
        heights.append(_height(pane.styles.height))
    return heights


# --- single-pane rendering is unchanged -----------------------------------


async def test_single_prompt_renders_one_solo_pane() -> None:
    app = _PromptBarApp("just one prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panes = app.query(".prompt-input")
        assert len(panes) == 1
        assert not app.query(".prompt-stack-separator")
        pane = app.query_one(".prompt-input", PromptTextArea)
        assert "solo" in pane.classes
        assert pane.text == "just one prompt"
        assert app.focused is pane


async def test_single_prompt_with_frontmatter_stays_verbatim() -> None:
    initial = "---\nmodel: opus\n---\ndo the thing"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        bar = app.query_one(PromptInputBar)
        # Frontmatter is NOT stripped for a single prompt; the pane is verbatim.
        assert bar.active_text() == initial


# --- multi-pane rendering --------------------------------------------------


async def test_initial_separators_render_stacked_panes() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        panes = app.query(".prompt-input")
        assert len(panes) == 3
        assert len(app.query(".prompt-stack-separator")) == 3
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        # Bottom pane is the default active pane and owns focus.
        assert bar._stack.selected_index == 2
        assert app.focused is bar.active_text_area()
        assert bar.active_text() == "third"
        assert "active" in bar.active_text_area().classes


async def test_stack_title_and_separator_surface_agent_count() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.border_title == "Prompt · 2 agents"

        separators = list(app.query(".prompt-stack-separator"))
        assert len(separators) == 2
        active_render = separators[1].render()
        assert "▍ agent 2" in active_render.plain
        assert active_render.plain.startswith("─")
        assert active_render.plain.endswith("─")

        bar.active_text_area()._enter_normal_mode()
        assert bar.border_title == "Prompt · 2 agents [NORMAL]"

        bar.load_stack_from_text("collapsed")
        await pilot.pause()
        await pilot.pause()

        assert bar.border_title == "Prompt"


async def test_panes_have_unique_ids() -> None:
    app = _PromptBarApp("a\n---\nb\n---\nc")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        ids = [pane.id for pane in app.query(".prompt-input")]
        assert len(ids) == len(set(ids)) == 3


async def test_current_prompt_text_joins_whole_stack() -> None:
    app = _PromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.current_prompt_text() == "alpha\n---\nbeta"


async def test_current_prompt_text_reflects_live_edits() -> None:
    app = _PromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Type into the active (bottom) pane.
        await pilot.press("!")
        await pilot.pause()

        assert bar.active_text() == "beta!"
        assert bar.all_prompt_texts() == ["alpha", "beta!"]
        assert bar.current_prompt_text() == "alpha\n---\nbeta!"


async def test_multi_prompt_with_frontmatter_preserved_on_join() -> None:
    app = _PromptBarApp("---\nmodel: opus\n---\nalpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["alpha", "beta"]
        joined = bar.current_prompt_text()
        assert joined == "---\nmodel: opus\n---\nalpha\n---\nbeta"


async def test_fenced_separator_does_not_split() -> None:
    initial = "before\n```\n---\nstill code\n```\nafter"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == initial


# --- height behavior -------------------------------------------------------


async def test_stack_height_capped_by_terminal_and_active_grows() -> None:
    long = "word " * 60  # wraps to many rows in a narrow terminal
    app = _PromptBarApp(f"short top\n---\nshort middle\n---\n{long}")

    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        heights = _pane_heights(app, bar)
        active = bar._stack.selected_index

        # The whole bar fits within the terminal (minus the reserved margin).
        assert _height(bar.styles.height) <= app.screen.size.height - 2
        # The active (long) bottom pane grows; the short inactive panes compact.
        assert heights[active] > max(heights[0], heights[1])


async def test_inactive_panes_compact_first() -> None:
    long = "word " * 60
    # Two long panes; only the active one is allowed to grow tall.
    app = _PromptBarApp(f"{long}\n---\n{long}")

    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        heights = _pane_heights(app, bar)
        active = bar._stack.selected_index
        inactive = 1 - active

        assert heights[active] > heights[inactive]
        assert _height(bar.styles.height) <= app.screen.size.height - 2


# --- focus + rebuild -------------------------------------------------------


async def test_focus_item_moves_active_pane() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.focus_item(0)
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.selected_index == 0
        assert app.focused is bar.active_text_area()
        assert bar.active_text() == "first"


async def test_load_stack_from_text_rebuilds_panes() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        bar.load_stack_from_text("uno\n---\ndos\n---\ntres")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 3
        assert bar.all_prompt_texts() == ["uno", "dos", "tres"]
        assert app.focused is bar.active_text_area()

        # And back down to a single pane.
        bar.load_stack_from_text("collapsed")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert "solo" in app.query_one(".prompt-input", PromptTextArea).classes
        assert bar.active_text() == "collapsed"


async def test_load_multi_agent_xprompt_invocation_stays_single_pane() -> None:
    """A ``#!`` multi-agent xprompt invocation has no literal ``---`` separators.

    Loading it from history must keep it as the authored single-pane invocation
    (the runner expands it into agents later), not split it into stacked panes.
    """
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_text("#!research_swarm investigate the flake")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "#!research_swarm investigate the flake"


async def test_load_single_cancelled_prompt_stays_single_pane() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_text("a previously cancelled prompt")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "a previously cancelled prompt"


# --- ^G edits the active pane only -----------------------------------------


async def test_update_active_pane_replaces_only_selected_pane() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.focus_item(1)  # edit the middle pane
        await pilot.pause()

        bar.update_active_pane("second EDITED")
        await pilot.pause()
        await pilot.pause()

        # Only the edited pane changed; the rest of the stack is intact.
        assert bar.all_prompt_texts() == ["first", "second EDITED", "third"]
        assert len(app.query(".prompt-input")) == 3
        assert bar._stack.selected_index == 1
        assert app.focused is bar.active_text_area()


async def test_is_stacked_reflects_pane_count() -> None:
    app = _PromptBarApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.is_stacked() is False

        bar.load_stack_from_text("a\n---\nb")
        await pilot.pause()
        await pilot.pause()
        assert bar.is_stacked() is True


# --- mode guards -----------------------------------------------------------


async def test_feedback_mode_never_splits() -> None:
    app = _PromptBarApp("a\n---\nb", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "a\n---\nb"


# --- all-pane editor (^⇧G) -------------------------------------------------


class _RecordingPromptBarApp(App[None]):
    """Host a prompt bar and record the editor messages it posts.

    Carries the app-level ``ctrl+g`` binding too, so a test can prove the
    focused pane's widget-local ``ctrl+g`` shadows it instead of triggering the
    global "edit last VCS xprompt" action.
    """

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [("ctrl+g", "start_last_vcs_xprompt_in_editor", "Edit last VCS")]

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.editor_requests: list[PromptInputBar.EditorRequested] = []
        self.all_editor_requests: list[PromptInputBar.AllEditorRequested] = []
        self.global_editor_calls = 0

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_editor_requested(
        self, event: PromptInputBar.EditorRequested
    ) -> None:
        self.editor_requests.append(event)

    def on_prompt_input_bar_all_editor_requested(
        self, event: PromptInputBar.AllEditorRequested
    ) -> None:
        self.all_editor_requests.append(event)

    def action_start_last_vcs_xprompt_in_editor(self) -> None:
        self.global_editor_calls += 1


async def test_ctrl_g_requests_active_pane_text_only() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.focus_item(1)  # edit the middle pane
        await pilot.pause()

        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # ^G posts only the active pane's text — never the all-editor message.
        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "second"
        assert app.all_editor_requests == []


async def test_ctrl_shift_g_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.active_text_area().action_open_all_editor()
        await pilot.pause()

        # ^⇧G posts the all-editor message; the serialized buffer is the whole
        # stack joined with ``---`` separators.
        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert bar.xprompt_markdown_for_editor() == "alpha\n---\nbeta"


async def test_all_editor_action_noop_in_feedback_mode() -> None:
    app = _RecordingPromptBarApp("draft feedback", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.active_text_area().action_open_all_editor()
        await pilot.pause()

        # The all-pane editor is a prompt-mode (multi-agent) surface only.
        assert app.all_editor_requests == []


async def test_focused_pane_ctrl_g_shadows_global_binding() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.focused is app.query_one(PromptInputBar).active_text_area()

        await pilot.press("ctrl+g")
        await pilot.pause()

        # The widget-local ^G wins: the editor request fires, the global
        # "edit last VCS xprompt" action never runs.
        assert len(app.editor_requests) == 1
        assert app.global_editor_calls == 0


def test_prompt_text_area_binds_both_editor_scopes() -> None:
    actions = {entry[0]: entry[1] for entry in PromptTextArea.BINDINGS}
    assert actions["ctrl+g"] == "open_editor"
    assert actions["ctrl+shift+g"] == "open_all_editor"


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

        # Canonical frontmatter sits above the panes, which keep launch order.
        assert markdown == f"{frontmatter}\nalpha\n---\nbeta"
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
        assert markdown == "alpha\n---\nbeta"
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


class _XPromptMarkdownApp(App[None]):
    """Minimal app that seeds a bar with editor-file (xprompt markdown) text."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, markdown: str) -> None:
        super().__init__()
        self._markdown = markdown

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_xprompt_markdown=self._markdown,
            id="prompt-input-bar",
        )


async def test_initial_xprompt_markdown_lifts_frontmatter_and_splits() -> None:
    """Constructor seeding with editor-file semantics lifts frontmatter + splits.

    The ``%edit`` editor-return remount path mounts a fresh bar via
    ``initial_xprompt_markdown=...``.  Unlike ``initial_value`` history-load
    semantics — where a single frontmatter prompt stays one verbatim pane (see
    ``test_single_prompt_with_frontmatter_stays_verbatim``) — this lifts leading
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
