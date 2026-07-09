"""Widget-level tests for core multi-agent prompt stack rendering (Phase 2).

Covers the Phase 2 deliverable of ``PromptInputBar``: initial text containing
``---`` separators renders as stacked panes, leading YAML frontmatter is lifted
onto the structured panel, the stack-aware helper APIs read the live panes, and
the stack height stays within the terminal with the active pane growing while
inactive panes compact.
"""

from __future__ import annotations

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_input_bar_stack_helpers import _PromptBarApp, _height, _pane_heights


# --- single-pane rendering ------------------------------------------------


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


async def test_single_prompt_with_frontmatter_lifts_to_panel() -> None:
    frontmatter = "---\ndescription: do the thing\n---"
    initial = f"{frontmatter}\nbody text"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        bar = app.query_one(PromptInputBar)
        assert bar.active_text() == "body text"
        assert bar._stack.frontmatter == frontmatter
        assert bar.current_prompt_text() == initial

        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        assert not panel.has_class("hidden")
        assert bar._stack.frontmatter_model.description == "do the thing"


async def test_single_plain_prompt_keeps_surrounding_whitespace_verbatim() -> None:
    initial = "  \n  just one prompt  \n  "
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == initial
        assert bar._stack.frontmatter == ""


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


async def test_stack_height_accounts_for_visible_frontmatter_panel() -> None:
    long = "word " * 120
    app = _PromptBarApp(
        "---\n"
        "description: keep the panel visible\n"
        "---\n"
        f"short top\n---\nshort middle\n---\n{long}"
    )

    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        heights = _pane_heights(app, bar)
        active = bar._stack.selected_index
        reserve = 2 + panel.reserved_height + len(heights)
        bar_height = _height(bar.styles.height)

        assert not panel.has_class("hidden")
        assert reserve + sum(heights) <= bar_height <= app.screen.size.height - 2
        assert heights[active] > max(
            height for index, height in enumerate(heights) if index != active
        )


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


async def test_load_stack_from_text_lifts_single_frontmatter_and_shows_panel() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        frontmatter = "---\ndescription: loaded from history\n---"
        bar.load_stack_from_text(f"{frontmatter}\ndo the thing")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "do the thing"
        assert bar._stack.frontmatter == frontmatter
        assert bar.current_prompt_text() == f"{frontmatter}\ndo the thing"
        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        assert not panel.has_class("hidden")


async def test_load_stack_from_text_lifts_multi_frontmatter_and_shows_panel() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        frontmatter = "---\ndescription: loaded multi\n---"
        bar.load_stack_from_text(f"{frontmatter}\nalpha\n---\nbeta")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["alpha", "beta"]
        assert bar._stack.frontmatter == frontmatter
        assert bar.current_prompt_text() == f"{frontmatter}\nalpha\n---\nbeta"
        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        assert not panel.has_class("hidden")


async def test_load_stack_from_text_plain_prompt_hides_frontmatter_panel() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_text("---\ndescription: loaded\n---\nbody")
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        assert not panel.has_class("hidden")

        bar.load_stack_from_text("plain body")
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.frontmatter == ""
        assert bar.active_text() == "plain body"
        assert panel.has_class("hidden")


async def test_load_xprompt_swarm_invocation_stays_single_pane() -> None:
    """An xprompt swarm invocation has no literal ``---`` separators.

    Loading it from history must keep it as the authored single-pane invocation
    (the runner expands it into agents later), not split it into stacked panes.
    """
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_text("#research_swarm investigate the flake")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "#research_swarm investigate the flake"


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


# --- update_active_pane edits only the selected pane -----------------------


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
