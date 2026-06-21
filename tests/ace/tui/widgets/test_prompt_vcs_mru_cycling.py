"""Regression: ``<ctrl+p>``/``<ctrl+n>`` cycle the bar text through the VCS MRU.

The launch-side identity is derived from the *submitted text*, so the cycled-to
ref must be exactly what the bar holds after cycling. These tests pin that text
plumbing so a future change can't reintroduce the stale-context desync that the
launch-side guards defend against.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.conftest import redirect_sase_home


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
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    parsing._VCS_TAG_EMBEDDED_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_EMBEDDED_PATTERN = None


class _CycleApp(App):
    # The real AceApp disables Textual's ctrl+p command palette so the prompt
    # bar can use ctrl+p for VCS MRU cycling; mirror that here.
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, *, mode: str | None = None) -> None:
        super().__init__()
        self._mode = mode

    def compose(self) -> ComposeResult:
        if self._mode is None:
            yield PromptTextArea()
        else:
            yield PromptInputBar(mode=self._mode)


async def _cycle(
    start_text: str,
    keys: str | Sequence[str],
    mru: list[str],
    *,
    cursor_offset: int | None = None,
    mode: str | None = None,
) -> tuple[str, int]:
    app = _CycleApp(mode=mode)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(start_text)
        ta.move_cursor(
            ta._location_from_absolute(
                len(start_text) if cursor_offset is None else cursor_offset
            )
        )
        ta.focus()
        with patch(
            "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
            return_value=mru,
        ):
            presses = (keys,) if isinstance(keys, str) else keys
            for key in presses:
                await pilot.press(key)
        return ta.text, ta._absolute_offset(ta.cursor_location)


async def _cycle_with_real_loader(
    start_text: str,
    keys: str | Sequence[str],
    *,
    cursor_offset: int | None = None,
) -> tuple[str, int]:
    """Cycle through the *real* launchable MRU loader (no loader patch).

    Used to assert that on-disk MRU entries excluded by
    ``load_launchable_vcs_xprompt_mru`` (e.g. the implicit ``#git:home``
    default) never surface as cyclable candidates in the widget.
    """
    app = _CycleApp()
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


async def test_cycling_skips_persisted_default_git_home_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persisted ``#git:home`` is filtered out, so cycling moves between the
    two surrounding non-default entries instead of landing on it."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:foo", "#git:home", "#git:bar"]}))

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"foo": workspace, "bar": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.changespec.cache.find_all_changespecs_cached",
        lambda *a, **k: [],
    )

    text, cursor = await _cycle_with_real_loader("#git:foo", "ctrl+p")

    assert text == "#git:bar "
    assert cursor == len("#git:bar ")


async def test_cycling_noops_when_only_mru_entry_is_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the only persisted entry is the default, the filtered MRU is empty
    and the cycle key is a no-op."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:home"]}))

    text, cursor = await _cycle_with_real_loader("", "ctrl+p")

    assert text == ""
    assert cursor == 0


async def test_ctrl_p_cycles_vcs_only_prompt_to_next_mru_entry() -> None:
    text, cursor = await _cycle(
        "#git:foo",
        "ctrl+p",
        ["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "#git:bar "
    assert cursor == len("#git:bar ")


async def test_ctrl_n_cycles_vcs_only_prompt_to_previous_mru_entry() -> None:
    text, cursor = await _cycle(
        "#git:bar",
        "ctrl+n",
        ["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "#git:foo "
    assert cursor == len("#git:foo ")


async def test_ctrl_p_cycles_empty_prompt_to_most_recent_entry() -> None:
    text, cursor = await _cycle("", "ctrl+p", ["#git:foo", "#git:bar"])
    assert text == "#git:foo "
    assert cursor == len("#git:foo ")


async def test_ctrl_p_replaces_tag_in_prompt_body() -> None:
    text, cursor = await _cycle(
        "#git:foo fix the bug",
        "ctrl+p",
        ["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar fix the bug"
    assert cursor == len("#git:bar fix the bug")


async def test_ctrl_p_replacement_keeps_cursor_at_logical_body_position() -> None:
    text, cursor = await _cycle(
        "#git:foo fix",
        "ctrl+p",
        ["#git:foo", "#git:longer"],
    )
    assert text == "#git:longer fix"
    assert cursor == len("#git:longer fix")


async def test_ctrl_p_prepends_tag_when_prompt_has_no_vcs_tag() -> None:
    text, cursor = await _cycle("fix the bug", "ctrl+p", ["#git:foo", "#git:bar"])
    assert text == "#git:foo fix the bug"
    assert cursor == len("#git:foo fix the bug")


async def test_second_prepend_cycle_replaces_prepended_tag() -> None:
    text, cursor = await _cycle(
        "fix the bug",
        ["ctrl+p", "ctrl+p"],
        ["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar fix the bug"
    assert cursor == len("#git:bar fix the bug")


async def test_ctrl_p_preserves_directives_when_replacing_tag() -> None:
    text, _cursor = await _cycle(
        "%n:a #git:foo fix",
        "ctrl+p",
        ["#git:foo", "#git:bar"],
    )
    assert text == "%n:a #git:bar fix"


async def test_ctrl_p_replaces_later_line_first_tag_only() -> None:
    text, _cursor = await _cycle(
        "intro\n#git:foo first\n---\n#git:baz second",
        "ctrl+p",
        ["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "intro\n#git:bar first\n---\n#git:baz second"


async def test_ctrl_p_preserves_newline_after_tag() -> None:
    text, _cursor = await _cycle(
        "#git:foo\nfix",
        "ctrl+p",
        ["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar\nfix"


async def test_feedback_mode_does_not_cycle_or_load_mru() -> None:
    app = _CycleApp(mode="feedback")
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta.focus()
        with patch(
            "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
            side_effect=AssertionError("feedback should not load MRU"),
        ):
            await pilot.press("ctrl+p")
        assert ta.text == ""


async def test_file_completion_keeps_ctrl_n_precedence() -> None:
    app = _CycleApp()
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
        with patch(
            "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
            side_effect=AssertionError("file completion should own ctrl+n"),
        ):
            await pilot.press("ctrl+n")
        assert ta.text == "fix"
        assert ta._file_completion_index == 1
