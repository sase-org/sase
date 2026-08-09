"""Widget tests for prompt VCS xprompt MRU cycling.

The launch-side identity is derived from the *submitted text*, so the prompt
text must reflect the active workspace tag after prompt-local key handling.
These tests pin ``Ctrl+P`` forward cycling, ``Ctrl+N`` backward cycling (which
clears the tag only at the reverse-cycle boundary), and completion-menu
precedence.
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
    and tag detection would never fire. Reset it before/after each test so the
    prompt key handlers see the actually-registered providers.
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


async def _press(
    start_text: str,
    keys: str | Sequence[str],
    *,
    mru: list[str] | None = None,
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
        presses = (keys,) if isinstance(keys, str) else keys
        if mru is None:
            for key in presses:
                await pilot.press(key)
        else:
            with patch(
                "sase.history.vcs_xprompt_mru.load_launchable_vcs_xprompt_mru",
                return_value=mru,
            ):
                for key in presses:
                    await pilot.press(key)
        return ta.text, ta._absolute_offset(ta.cursor_location)


async def _press_with_real_loader(
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
    return await _press(start_text, keys, cursor_offset=cursor_offset)


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
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )

    text, cursor = await _press_with_real_loader("#git:foo", "ctrl+p")

    assert text == "#git:bar "
    assert cursor == len("#git:bar ")


async def test_cycling_inserts_humanized_configured_project_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycling surfaces the configured ``PROJECT_NAME``, never the directory key.

    The on-disk MRU stays canonical (``#git:proj_widgets``); the real loader
    humanizes it to ``#git:widgets`` before it reaches the cycling widget.
    """
    import sase.project_display_names as pdn

    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    project_dir = sase_home / "projects" / "proj_widgets"
    project_dir.mkdir(parents=True)
    (project_dir / "proj_widgets.sase").write_text(
        f"PROJECT_NAME: widgets\nWORKSPACE_DIR: {workspace}\nNAME: proj_widgets_c\n",
        encoding="utf-8",
    )
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:proj_widgets"]}))

    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *a, **k: {"proj_widgets": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    text, cursor = await _press_with_real_loader("", "ctrl+p")

    assert text == "#git:widgets "
    assert cursor == len("#git:widgets ")
    # Disk stays canonical for launch-time identity/resolution.
    assert json.loads(mru_file.read_text()) == {"entries": ["#git:proj_widgets"]}


async def test_cycling_noops_when_only_mru_entry_is_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the only persisted entry is the default, the filtered MRU is empty
    and the cycle key is a no-op."""
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    mru_file = sase_home / "vcs_xprompt_mru.json"
    mru_file.write_text(json.dumps({"entries": ["#git:home"]}))

    text, cursor = await _press_with_real_loader("", "ctrl+p")

    assert text == ""
    assert cursor == 0


async def test_ctrl_p_cycles_vcs_only_prompt_to_next_mru_entry() -> None:
    text, cursor = await _press(
        "#git:foo",
        "ctrl+p",
        mru=["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "#git:bar "
    assert cursor == len("#git:bar ")


async def test_ctrl_p_cycles_through_empty_stop_and_wraps() -> None:
    text, cursor = await _press(
        "#git:foo",
        ["ctrl+p", "ctrl+p", "ctrl+p"],
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "#git:foo "
    assert cursor == len("#git:foo ")


async def test_ctrl_p_reaches_empty_stop_from_oldest_entry() -> None:
    text, cursor = await _press(
        "#git:bar",
        "ctrl+p",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == ""
    assert cursor == 0


async def test_ctrl_p_empty_stop_removes_tag_before_body() -> None:
    text, cursor = await _press(
        "#git:bar fix the bug",
        "ctrl+p",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "fix the bug"
    assert cursor == len("fix the bug")


async def test_ctrl_n_at_most_recent_entry_deletes_tag_only_prompt() -> None:
    """Reverse-cycling off the most recent entry hits the empty stop, which
    clears a tag-only prompt."""
    text, cursor = await _press(
        "#git:foo",
        "ctrl+n",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == ""
    assert cursor == 0


async def test_ctrl_n_at_most_recent_entry_deletes_first_vcs_tag() -> None:
    text, cursor = await _press(
        "#git:foo fix the bug",
        "ctrl+n",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "fix the bug"
    assert cursor == len("fix the bug")


async def test_ctrl_n_preserves_directives_when_deleting_tag() -> None:
    text, _cursor = await _press(
        "%i:a #git:foo fix",
        "ctrl+n",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "%i:a fix"


async def test_ctrl_n_cycles_backward_to_newer_entry() -> None:
    text, cursor = await _press(
        "#git:bar",
        "ctrl+n",
        mru=["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "#git:foo "
    assert cursor == len("#git:foo ")


async def test_ctrl_n_from_no_vcs_tag_selects_oldest_entry() -> None:
    text, cursor = await _press(
        "fix the bug",
        "ctrl+n",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar fix the bug"
    assert cursor == len("#git:bar fix the bug")


async def test_ctrl_n_empty_prompt_selects_oldest_entry() -> None:
    text, cursor = await _press("", "ctrl+n", mru=["#git:foo", "#git:bar"])
    assert text == "#git:bar "
    assert cursor == len("#git:bar ")


async def test_ctrl_n_only_fenced_block_tag_prepends_and_keeps_quote() -> None:
    """A tag quoted inside a fenced block is not a workflow ref, so cycling
    prepends an MRU entry instead of touching the quoted tag."""
    start = "Fix the launcher:\n```\nsase run #git:quoted do thing\n```\n"
    text, _cursor = await _press(start, "ctrl+n", mru=["#git:foo", "#git:bar"])
    assert text.startswith("#git:bar ")
    assert "#git:quoted" in text


async def test_ctrl_p_ctrl_n_round_trip_returns_to_starting_tag() -> None:
    text, cursor = await _press(
        "#git:foo",
        ["ctrl+p", "ctrl+p", "ctrl+n", "ctrl+n"],
        mru=["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "#git:foo "
    assert cursor == len("#git:foo ")


async def test_ctrl_p_cycles_empty_prompt_to_most_recent_entry() -> None:
    text, cursor = await _press("", "ctrl+p", mru=["#git:foo", "#git:bar"])
    assert text == "#git:foo "
    assert cursor == len("#git:foo ")


async def test_ctrl_p_replaces_tag_in_prompt_body() -> None:
    text, cursor = await _press(
        "#git:foo fix the bug",
        "ctrl+p",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar fix the bug"
    assert cursor == len("#git:bar fix the bug")


async def test_ctrl_p_replacement_keeps_cursor_at_logical_body_position() -> None:
    text, cursor = await _press(
        "#git:foo fix",
        "ctrl+p",
        mru=["#git:foo", "#git:longer"],
    )
    assert text == "#git:longer fix"
    assert cursor == len("#git:longer fix")


async def test_ctrl_p_prepends_tag_when_prompt_has_no_vcs_tag() -> None:
    text, cursor = await _press(
        "fix the bug",
        "ctrl+p",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "#git:foo fix the bug"
    assert cursor == len("#git:foo fix the bug")


async def test_second_prepend_cycle_replaces_prepended_tag() -> None:
    text, cursor = await _press(
        "fix the bug",
        ["ctrl+p", "ctrl+p"],
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar fix the bug"
    assert cursor == len("#git:bar fix the bug")


async def test_ctrl_p_preserves_directives_when_replacing_tag() -> None:
    text, _cursor = await _press(
        "%i:a #git:foo fix",
        "ctrl+p",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "%i:a #git:bar fix"


async def test_ctrl_p_replaces_later_line_first_tag_only() -> None:
    text, _cursor = await _press(
        "intro\n#git:foo first\n---\n#git:baz second",
        "ctrl+p",
        mru=["#git:foo", "#git:bar", "#git:baz"],
    )
    assert text == "intro\n#git:bar first\n---\n#git:baz second"


async def test_ctrl_p_preserves_newline_after_tag() -> None:
    text, _cursor = await _press(
        "#git:foo\nfix",
        "ctrl+p",
        mru=["#git:foo", "#git:bar"],
    )
    assert text == "#git:bar\nfix"


async def test_feedback_mode_does_not_cycle_delete_or_load_mru() -> None:
    app = _CycleApp(mode="feedback")
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


async def test_file_completion_keeps_ctrl_p_precedence() -> None:
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
        ta._file_completion_index = 1
        await pilot.press("ctrl+p")
        assert ta.text == "fix"
        assert ta._file_completion_index == 0
