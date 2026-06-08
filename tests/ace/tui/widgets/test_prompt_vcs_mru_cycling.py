"""Regression: ``<ctrl+p>``/``<ctrl+n>`` cycle the bar text through the VCS MRU.

The launch-side identity is derived from the *submitted text*, so the cycled-to
ref must be exactly what the bar holds after cycling. These tests pin that text
plumbing so a future change can't reintroduce the stale-context desync that the
launch-side guards defend against.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers.

    Other tests in the suite patch workflow metadata to a reduced set; if the
    global VCS tag pattern was built during that window it would drop ``#git``
    and ``is_vcs_only`` detection would never fire. Reset it before/after each
    test so cycling sees the actually-registered providers.
    """
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None


class _CycleApp(App):
    # The real AceApp disables Textual's ctrl+p command palette so the prompt
    # bar can use ctrl+p for VCS MRU cycling; mirror that here.
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield PromptTextArea()


async def _cycle(start_text: str, key: str, mru: list[str]) -> str:
    app = _CycleApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(start_text)
        ta.move_cursor((0, len(start_text)))
        ta.focus()
        with patch(
            "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
            return_value=mru,
        ):
            await pilot.press(key)
        return ta.text


async def test_ctrl_p_cycles_vcs_only_prompt_to_next_mru_entry() -> None:
    text = await _cycle("#git:foo", "ctrl+p", ["#git:foo", "#git:bar", "#git:baz"])
    assert text == "#git:bar "


async def test_ctrl_n_cycles_vcs_only_prompt_to_previous_mru_entry() -> None:
    text = await _cycle("#git:bar", "ctrl+n", ["#git:foo", "#git:bar", "#git:baz"])
    assert text == "#git:foo "
