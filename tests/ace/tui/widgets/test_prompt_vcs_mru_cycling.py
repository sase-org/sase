"""Widget tests: prompt ``<ctrl+n>`` deletes the first VCS xprompt tag.

``<ctrl+n>`` removes the first real VCS workflow tag (e.g. ``#git:foo``) from
the prompt body and is otherwise a prompt-local no-op; ``<ctrl+p>`` is always a
prompt-local no-op. Neither key loads MRU history. These tests pin that text
plumbing and confirm file-completion navigation keeps precedence over both keys.
"""

from __future__ import annotations

from collections.abc import Sequence
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers.

    Other tests in the suite patch workflow metadata to a reduced set; if the
    global VCS tag pattern was built during that window it would drop ``#git``
    and tag detection would never fire. Reset it before/after each test so the
    delete path sees the actually-registered providers.
    """
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None


class _PromptApp(App):
    # The real AceApp disables Textual's ctrl+p command palette so the prompt
    # bar owns ctrl+p; mirror that here.
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, *, mode: str | None = None) -> None:
        super().__init__()
        self._mode = mode

    def compose(self) -> ComposeResult:
        if self._mode is None:
            yield PromptTextArea()
        else:
            yield PromptInputBar(mode=self._mode)


async def _press(
    start_text: str,
    keys: str | Sequence[str],
    *,
    cursor_offset: int | None = None,
    mode: str | None = None,
) -> tuple[str, int]:
    app = _PromptApp(mode=mode)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(start_text)
        ta.move_cursor(
            ta._location_from_absolute(
                len(start_text) if cursor_offset is None else cursor_offset
            )
        )
        ta.focus()
        presses = (keys,) if isinstance(keys, str) else keys
        for key in presses:
            await pilot.press(key)
        return ta.text, ta._absolute_offset(ta.cursor_location)


async def test_ctrl_n_deletes_first_vcs_tag() -> None:
    text, cursor = await _press("#git:foo fix the bug", "ctrl+n")
    assert text == "fix the bug"
    assert cursor == len("fix the bug")


async def test_ctrl_n_deletes_tag_only_prompt_to_empty() -> None:
    text, cursor = await _press("#git:foo", "ctrl+n")
    assert text == ""
    assert cursor == 0


async def test_ctrl_n_preserves_directives_when_deleting_tag() -> None:
    text, _cursor = await _press("%n:a #git:foo fix", "ctrl+n")
    assert text == "%n:a fix"


async def test_ctrl_n_noop_when_prompt_has_no_vcs_tag() -> None:
    text, _cursor = await _press("fix the bug", "ctrl+n")
    assert text == "fix the bug"


async def test_ctrl_n_noop_when_only_fenced_block_tag_exists() -> None:
    """A tag quoted inside a fenced block is not a workflow ref, so it stays."""
    start = "Fix the launcher:\n```\nsase run #git:quoted do thing\n```\n"
    text, _cursor = await _press(start, "ctrl+n")
    assert text == start


async def test_ctrl_p_is_prompt_local_noop() -> None:
    text, cursor = await _press("#git:foo fix the bug", "ctrl+p")
    assert text == "#git:foo fix the bug"
    assert cursor == len("#git:foo fix the bug")


async def test_ctrl_n_and_ctrl_p_do_not_load_mru() -> None:
    with patch(
        "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
        side_effect=AssertionError("prompt delete must not load MRU"),
    ):
        text, _cursor = await _press("#git:foo fix", ["ctrl+p", "ctrl+n"])
    # ctrl+p is a no-op; ctrl+n then deletes the tag -- neither loaded MRU.
    assert text == "fix"


async def test_feedback_mode_ctrl_n_does_not_delete_or_load_mru() -> None:
    app = _PromptApp(mode="feedback")
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo fix")
        ta.focus()
        with patch(
            "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
            side_effect=AssertionError("feedback should not load MRU"),
        ):
            await pilot.press("ctrl+n")
            await pilot.press("ctrl+p")
        assert ta.text == "#git:foo fix"


async def test_file_completion_keeps_ctrl_n_precedence() -> None:
    app = _PromptApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("fix")
        ta.focus()
        ta._file_completion_active = True
        ta._file_completion_candidates = [
            CompletionCandidate("a", "a", False, "a"),
            CompletionCandidate("b", "b", False, "b"),
        ]
        ta._file_completion_index = 0
        await pilot.press("ctrl+n")
        assert ta.text == "fix"
        assert ta._file_completion_index == 1


async def test_file_completion_keeps_ctrl_p_precedence() -> None:
    app = _PromptApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("fix")
        ta.focus()
        ta._file_completion_active = True
        ta._file_completion_candidates = [
            CompletionCandidate("a", "a", False, "a"),
            CompletionCandidate("b", "b", False, "b"),
        ]
        ta._file_completion_index = 1
        await pilot.press("ctrl+p")
        assert ta.text == "fix"
        assert ta._file_completion_index == 0
