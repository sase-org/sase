"""Tests for the ``#+`` VCS-project completion menu in the prompt widget.

Covers the Phase-2 TUI wiring on top of the Phase-1 headless helpers: trigger
auto-open, query filtering, ``ctrl+n/p`` navigation, accept applying the
canonical expansion end-to-end (representative golden vectors), replacing an
existing leading tag, the empty-catalog placeholder, and dismissal. The full
golden-vector table is the parity contract and is exhaustively asserted at the
helper level in ``tests/test_xprompt_vcs_project_completion.py``.
"""

from __future__ import annotations

from typing import Literal
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.vcs_project_completion import (
    VCS_PROJECT_COMPLETION_KIND,
    build_no_active_projects_placeholder,
    vcs_project_completion_candidates,
)
from sase.xprompt.vcs_project_completion import VcsProjectEntry

from ._completion_helpers import CompletionTestApp

_ENTRIES_PATH = (
    "sase.ace.tui.widgets.vcs_project_completion.build_vcs_project_completion_entries"
)
_DISPLAY_NAME_PATH = (
    "sase.ace.tui.widgets._prompt_input_bar_completion_rows.project_display_name_for"
)


def _entry(
    name: str,
    *,
    vcs: str = "gh",
    provider: str = "GitHub",
    description: str = "",
    aliases: tuple[str, ...] = (),
    kind: Literal["project", "changespec"] = "project",
    project: str | None = None,
    status: str = "",
) -> VcsProjectEntry:
    return VcsProjectEntry(
        name=name,
        vcs_prefix=vcs,
        display_tag=f"#{vcs}:{name}",
        provider_display=provider,
        description=description,
        aliases=aliases,
        kind=kind,
        project=project or name,
        status=status,
    )


# Name-sorted, like the real catalog builder returns.
_PROJECTS = [
    _entry("sase", description="SASE core repo"),
    _entry("telegram", vcs="git", provider="Git", aliases=("tg",)),
    _entry("widgets"),
]

_PROJECTS_AND_PRS = [
    *_PROJECTS,
    _entry(
        "ship-completion",
        kind="changespec",
        project="sase",
        status="Ready",
    ),
]


# --- Pure helpers ----------------------------------------------------------


def test_candidates_flags_empty_catalog() -> None:
    candidates, catalog_empty = vcs_project_completion_candidates("", entries=[])
    assert candidates == []
    assert catalog_empty is True


def test_candidates_unfiltered_returns_all_in_order() -> None:
    candidates, catalog_empty = vcs_project_completion_candidates("", entries=_PROJECTS)
    assert catalog_empty is False
    assert [c.name for c in candidates] == ["sase", "telegram", "widgets"]
    # Each candidate carries its entry as metadata for the renderer.
    assert all(isinstance(c.metadata, VcsProjectEntry) for c in candidates)
    assert candidates[0].insertion == "#gh:sase"


def test_candidates_prefix_filter_is_case_insensitive() -> None:
    candidates, _ = vcs_project_completion_candidates("SA", entries=_PROJECTS)
    assert [c.name for c in candidates] == ["sase"]


def test_candidates_match_alias_prefix() -> None:
    candidates, _ = vcs_project_completion_candidates("tg", entries=_PROJECTS)
    assert [c.name for c in candidates] == ["telegram"]


def test_candidates_non_empty_catalog_no_match() -> None:
    candidates, catalog_empty = vcs_project_completion_candidates(
        "zzz", entries=_PROJECTS
    )
    assert candidates == []
    assert catalog_empty is False


def test_placeholder_is_non_selectable() -> None:
    placeholder = build_no_active_projects_placeholder()
    assert placeholder.metadata is None
    assert "no enabled projects or PRs" in placeholder.display


def test_candidates_include_changespec_metadata() -> None:
    candidates, catalog_empty = vcs_project_completion_candidates(
        "ship",
        entries=_PROJECTS_AND_PRS,
    )
    assert catalog_empty is False
    assert [c.name for c in candidates] == ["ship-completion"]
    entry = candidates[0].metadata
    assert isinstance(entry, VcsProjectEntry)
    assert entry.kind == "changespec"
    assert entry.project == "sase"
    assert entry.status == "Ready"


# --- Trigger auto-open -----------------------------------------------------


async def test_hash_plus_auto_opens_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            assert ta.text == "#"
            assert ta._file_completion_active is False
            await pilot.press("+")

        assert ta.text == "#+"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "projects & PRs"
        rendered = panel.render().plain
        assert "sase" in rendered
        assert "telegram" in rendered
        # The provider and resulting tag are shown as part of the row.
        assert "GitHub" in rendered
        assert "#gh:sase" in rendered


async def test_bare_plus_at_bof_auto_opens_menu() -> None:
    """A ``+`` at the very beginning of the prompt opens project completion."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")

        assert ta.text == "+"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "projects & PRs"
        rendered = panel.render().plain
        assert "sase" in rendered
        assert "telegram" in rendered


async def test_menu_renders_project_and_changespec_badges() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS_AND_PRS):
            await pilot.press("#")
            await pilot.press("+")

        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "projects & PRs"
        rendered = panel.render().plain
        assert "[P] sase" in rendered
        assert "[PR] ship-completion" in rendered
        assert "#gh:ship-completion" in rendered
        assert "Ready" in rendered
        assert "· sase" in rendered


async def test_menu_renders_changespec_project_display_name() -> None:
    app = CompletionTestApp()
    entries = [
        _entry(
            "ship-completion",
            kind="changespec",
            project="gh_acme__widgets",
            status="Ready",
        )
    ]
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        with (
            patch(_ENTRIES_PATH, return_value=entries),
            patch(
                _DISPLAY_NAME_PATH,
                side_effect=lambda key: {"gh_acme__widgets": "widgets"}.get(key, key),
            ),
        ):
            await pilot.press("#")
            await pilot.press("+")

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render().plain
        assert "· widgets" in rendered
        assert "gh_acme__widgets" not in rendered


async def test_bare_plus_after_text_does_not_open() -> None:
    """A bare ``+`` triggers only at offset 0, not after existing text."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix")
        ta.cursor_location = (0, 3)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("space")
            await pilot.press("+")

        assert ta.text == "Fix +"
        assert ta._file_completion_active is False


async def test_bare_plus_after_whitespace_does_not_open() -> None:
    """A bare ``+`` after a leading space is ordinary text."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(" ")
        ta.cursor_location = (0, 1)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")

        assert ta.text == " +"
        assert ta._file_completion_active is False


async def test_hash_plus_after_word_does_not_open() -> None:
    """A ``#+`` embedded in a word is ordinary text."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("c")
        ta.cursor_location = (0, 1)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")

        assert ta.text == "c#+"
        assert ta._file_completion_active is False


async def test_typing_filters_candidates() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")
            assert len(ta._file_completion_candidates) == 3

            # Typing forward narrows the list by case-insensitive name prefix.
            await pilot.press("t")
            assert ta.text == "#+t"
            assert [c.name for c in ta._file_completion_candidates] == ["telegram"]


async def test_ctrl_n_p_cycle_highlight() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")
            assert ta._file_completion_index == 0
            await pilot.press("ctrl+n")
            assert ta._file_completion_index == 1
            await pilot.press("ctrl+p")
            assert ta._file_completion_index == 0
            await pilot.press("ctrl+p")
            assert ta._file_completion_index == 2  # wraps to the end


# --- Accept (canonical expansion, representative golden vectors) ------------


def _select(ta: PromptTextArea, name: str) -> None:
    """Highlight the candidate whose project name is *name*."""
    index = next(
        i for i, c in enumerate(ta._file_completion_candidates) if c.name == name
    )
    ta._file_completion_index = index


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#+", "#gh:sase "),  # golden #2
        ("#+sa", "#gh:sase "),  # golden #3
        ("Describe this repo. #+", "#gh:sase Describe this repo."),  # golden #1
        ("#git:foo Fix bug #+", "#gh:sase Fix bug"),  # golden #4 (replace)
        # Existing leading tag at end-of-input must be replaced, not doubled
        # (the `#gh:sase #+` regression; uses `#git:foo` here since only `git`
        # is a registered workflow name in the test environment).
        ("#git:foo #+", "#gh:sase "),
        ("Line one\n#+", "#gh:sase Line one\n"),  # golden #7 (multi-line)
        ("%model:opus Body #+", "%model:opus #gh:sase Body"),  # golden #9
    ],
)
async def test_accept_applies_canonical_expansion(text: str, expected: str) -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(text)
        ta.cursor_location = ta._location_from_absolute(len(text))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            assert ta._try_vcs_project_completion() is True
        _select(ta, "sase")
        await pilot.press("ctrl+l")

        assert ta.text == expected
        assert ta._file_completion_active is False


async def test_bare_plus_accept_expands_to_tag() -> None:
    """Accepting a bare ``+`` selection prepends the project's VCS tag."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert ta._file_completion_active is True
        _select(ta, "sase")
        await pilot.press("ctrl+l")

        assert ta.text == "#gh:sase "
        assert ta._file_completion_active is False


async def test_bare_plus_query_filters_and_accepts() -> None:
    """Typing after a BOF ``+`` filters, and accept expands the match."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            await pilot.press("t")
            await pilot.press("e")
            assert ta.text == "+te"
            assert [c.name for c in ta._file_completion_candidates] == ["telegram"]
        await pilot.press("ctrl+l")

        assert ta.text == "#git:telegram "
        assert ta._file_completion_active is False


async def test_ctrl_t_on_bof_plus_token_opens_menu() -> None:
    """Ctrl+T on an existing ``+query`` token at prompt start opens the menu."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("+te")
        ta.cursor_location = (0, len("+te"))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        assert [c.name for c in ta._file_completion_candidates] == ["telegram"]


async def test_accept_places_cursor_after_inserted_tag() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")
        _select(ta, "sase")
        await pilot.press("ctrl+l")

        assert ta.text == "#gh:sase "
        assert ta.cursor_location == (0, len("#gh:sase "))


# --- Empty catalog & dismissal ---------------------------------------------


async def test_empty_catalog_shows_placeholder_row() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=[]):
            await pilot.press("#")
            await pilot.press("+")

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        assert len(ta._file_completion_candidates) == 1
        assert ta._file_completion_candidates[0].metadata is None
        panel = bar.query_one("#prompt-completion", Static)
        assert "no enabled projects or PRs" in panel.render().plain


async def test_accept_placeholder_is_noop() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=[]):
            await pilot.press("#")
            await pilot.press("+")
        await pilot.press("ctrl+l")

        assert ta.text == "#+"
        assert ta._file_completion_active is False


async def test_space_after_token_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")
            assert ta._file_completion_active is True
            await pilot.press("space")

        assert ta.text == "#+ "
        assert ta._file_completion_active is False


async def test_non_matching_query_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")
            assert ta._file_completion_active is True
            await pilot.press("z")  # no project starts with "z"

        assert ta.text == "#+z"
        assert ta._file_completion_active is False


async def test_escape_dismisses_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")
            assert ta._file_completion_active is True
            await pilot.press("escape")

        assert ta._file_completion_active is False


async def test_ctrl_t_on_existing_plus_token_opens_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Review #+te")
        ta.cursor_location = (0, len("Review #+te"))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        assert [c.name for c in ta._file_completion_candidates] == ["telegram"]
