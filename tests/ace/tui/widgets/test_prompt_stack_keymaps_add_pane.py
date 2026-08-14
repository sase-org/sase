"""Prompt-stack keymap tests for adding panes."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals.snippet_name_modal import SnippetNameResult
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.snippet_targets import SnippetSaveTarget

from ._prompt_stack_keymap_helpers import PromptStackKeymapApp


def _snippet_result(
    tmp_path: Path,
    *,
    existing_body: str = "snippet body",
) -> SnippetNameResult:
    path = tmp_path / "sase.yml"
    target = SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path="~/sase.yml",
        source="configured",
        fallback_reason=None,
    )
    return SnippetNameResult(
        trigger="todo",
        target=target,
        exists=True,
        existing_body=existing_body,
        derived_from=None,
    )


# --- add a bottom pane (NORMAL-mode g-) ------------------------------------


async def test_g_minus_adds_bottom_pane_from_normal() -> None:
    """``g-`` inherits the active pane's explicit VCS tag."""
    app = PromptStackKeymapApp("#git:sase")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["#git:sase", "#git:sase "]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "#git:sase "
        assert app.focused is bar.active_text_area()
        # The fresh pane is ready to type in.
        assert bar.active_text_area()._vim_mode == "insert"


async def test_ctrl_g_minus_adds_bottom_pane_from_insert() -> None:
    """``Ctrl+G -`` reaches the same inherited-tag add-pane action."""
    app = PromptStackKeymapApp("#git:home solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+g", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["#git:home solo prompt", "#git:home "]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "#git:home "
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_minus_adds_empty_pane_without_explicit_vcs_tag() -> None:
    """Bare prompts still append an empty pane."""
    app = PromptStackKeymapApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["solo prompt", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_minus_inherits_tag_after_directives_without_body() -> None:
    """Only the VCS tag is copied, not leading directives or task text."""
    app = PromptStackKeymapApp("%i:agent-a %model:opus #git:sase Fix the bug")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == [
            "%i:agent-a %model:opus #git:sase Fix the bug",
            "#git:sase ",
        ]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "#git:sase "
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_minus_inherits_from_selected_pane() -> None:
    """A multi-pane stack inherits from the selected pane, not the first pane."""
    app = PromptStackKeymapApp("#git:first first task\n---\n#git:second second task")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 1

        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == [
            "#git:first first task",
            "#git:second second task",
            "#git:second ",
        ]
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "#git:second "


async def test_g_minus_uses_current_pane_after_focus_change() -> None:
    """Selecting an earlier pane changes the inherited VCS tag."""
    app = PromptStackKeymapApp("#git:first first task\n---\n#git:second second task")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "k")
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == [
            "#git:first first task",
            "#git:second second task",
            "#git:first ",
        ]
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "#git:first "


async def test_ctrl_g_minus_from_snippet_focus_adds_empty_agent_above_snippet(
    tmp_path: Path,
) -> None:
    """A focused snippet target is not a VCS source."""
    app = PromptStackKeymapApp("#git:sase agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.open_snippet_target_pane(
            _snippet_result(tmp_path, existing_body="#git:snippet body"),
            origin_pane_id=bar.active_text_area().id or "",
            destination_exists=True,
            loaded_fingerprint=None,
        )
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.selected_item.is_snippet_pane
        assert bar._stack.snippet_index == 1

        await pilot.press("ctrl+g", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 3
        assert bar.all_prompt_texts() == ["#git:sase agent prompt", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert bar._stack.snippet_index == 2
        assert bar._stack.items[2].text == "#git:snippet body"
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_minus_is_normal_mode_only() -> None:
    """``g-`` is NORMAL-mode-only: in insert mode the keys type literally."""
    app = PromptStackKeymapApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; ``g`` then ``-`` are ordinary characters.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        # No new pane: the chord was typed into the active pane verbatim.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo promptg-"]


async def test_plain_dash_no_longer_adds_pane_in_normal() -> None:
    """A bare ``-`` (no ``g`` prefix) does not mutate the stack in normal mode."""
    app = PromptStackKeymapApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("-")
        await pilot.pause()
        await pilot.pause()

        # Plain hyphen is inert in normal mode (read-only): no new pane, and the
        # existing prompt text is untouched.  Add-pane lives on ``g-`` now.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo prompt"]


@pytest.mark.parametrize("add_pane_key", ("ctrl+minus", "ctrl+underscore"))
async def test_ctrl_minus_no_longer_adds_pane(add_pane_key: str) -> None:
    """The retired ``Ctrl+-`` / ``ctrl+underscore`` chords no longer add a pane.

    Textual reports legacy ``0x1f`` as ``ctrl+underscore`` (also Ctrl-hyphen),
    so this covers both the Kitty CSI-u and tmux / legacy terminal paths; both
    are inert now that add-pane migrated to the NORMAL-mode ``g-`` keymap.
    """
    app = PromptStackKeymapApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        # From insert (the old chord worked while typing) ...
        await pilot.press(add_pane_key)
        await pilot.pause()
        await pilot.pause()
        # ... and from normal (the old chord worked while browsing too).
        await pilot.press("escape")
        await pilot.press(add_pane_key)
        await pilot.pause()
        await pilot.pause()

        # Still a single pane: the legacy chord adds nothing in either mode.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo prompt"]


async def test_g_minus_is_noop_in_feedback_mode() -> None:
    app = PromptStackKeymapApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["feedback text"]
