"""Tests for the ``+`` VCS-project completion menu in the prompt widget.

Covers trigger auto-open, query filtering, ``ctrl+n/p`` navigation, core
in-place acceptance (representative vectors), project switching, the
empty-catalog placeholder, and dismissal. The full golden-vector table for
the core trigger/accept pair lives in the core's ``project_tag/tests.rs``.
"""

from __future__ import annotations

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
from sase.xprompt.vcs_project_completion import VcsProjectEntry, VcsProjectEntryKind

from ._completion_helpers import CompletionTestApp

_ENTRIES_PATH = (
    "sase.ace.tui.widgets.vcs_project_completion.build_vcs_project_completion_entries"
)
_DISPLAY_NAME_PATH = (
    "sase.ace.tui.widgets._prompt_input_bar_completion_rows_vcs."
    "project_display_name_for"
)


def _entry(
    name: str,
    *,
    vcs: str = "gh",
    provider: str = "GitHub",
    description: str = "",
    aliases: tuple[str, ...] = (),
    kind: VcsProjectEntryKind = "project",
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
        key=(project or name) if kind == "project" else "",
        tag=f"+{name}" if kind == "project" else "",
        accent_index=0 if kind == "project" else None,
        current=False if kind == "project" else None,
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
        kind="patch",
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
    # Project rows insert the tag (with the row's own trailing separator);
    # PR rows insert their ``#`` ref.
    assert candidates[0].insertion == "+sase "


def test_candidate_insertions_use_tags_for_projects() -> None:
    candidates, _ = vcs_project_completion_candidates("", entries=_PROJECTS_AND_PRS)
    by_name = {c.name: c.insertion for c in candidates}
    assert by_name["sase"] == "+sase "
    assert by_name["telegram"] == "+telegram "
    assert by_name["ship-completion"] == "#gh:ship-completion "


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


def test_candidates_include_patch_metadata() -> None:
    candidates, catalog_empty = vcs_project_completion_candidates(
        "ship",
        entries=_PROJECTS_AND_PRS,
    )
    assert catalog_empty is False
    assert [c.name for c in candidates] == ["ship-completion"]
    entry = candidates[0].metadata
    assert isinstance(entry, VcsProjectEntry)
    assert entry.kind == "patch"
    assert entry.project == "sase"
    assert entry.status == "Ready"


# --- Trigger auto-open -----------------------------------------------------


async def test_space_delimited_plus_auto_opens_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix ")
        ta.cursor_location = (0, len("Fix "))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")

        assert ta.text == "Fix +"
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


async def test_menu_renders_project_tags_and_patch_badges() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS_AND_PRS):
            await pilot.press("+")

        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "projects & PRs"
        rendered = panel.render().plain
        # Project rows render the accent-colored tag, never a badge.
        assert "+sase" in rendered
        assert "[P]" not in rendered
        assert "GitHub · #gh:sase" in rendered
        # Patch rows keep their badge, status, and owning project.
        assert "[PR] ship-completion" in rendered
        assert "Ready" in rendered
        assert "· sase" in rendered


async def test_menu_renders_patch_project_display_name() -> None:
    app = CompletionTestApp()
    entries = [
        _entry(
            "ship-completion",
            kind="patch",
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
            await pilot.press("+")

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render().plain
        assert "· widgets" in rendered
        assert "gh_acme__widgets" not in rendered


async def test_glued_plus_after_text_does_not_open() -> None:
    """A ``+`` glued to an existing word is ordinary text."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix")
        ta.cursor_location = (0, 3)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")

        assert ta.text == "Fix+"
        assert ta._file_completion_active is False


@pytest.mark.parametrize("prefix", ["\t", "line\n", "%{", "%{a | "])
async def test_plus_at_d1_boundaries_opens(prefix: str) -> None:
    """Tabs, newlines, and alt-group boundaries satisfy the D1 trigger rule."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(prefix)
        ta.cursor_location = ta._location_from_absolute(len(prefix))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")

        assert ta.text == f"{prefix}+"
        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND


@pytest.mark.parametrize("prefix", ["", "Fix ", "c"])
async def test_hash_plus_does_not_open(prefix: str) -> None:
    """``#+`` is ordinary text at BOF, after a space, and inside a word."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(prefix)
        ta.cursor_location = (0, len(prefix))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("#")
            await pilot.press("+")

        assert ta.text == f"{prefix}#+"
        assert ta._file_completion_active is False


async def test_typing_filters_candidates() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix ")
        ta.cursor_location = (0, len("Fix "))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert len(ta._file_completion_candidates) == 3

            # Typing forward narrows the list by case-insensitive name prefix.
            await pilot.press("t")
            assert ta.text == "Fix +t"
            assert [c.name for c in ta._file_completion_candidates] == ["telegram"]


async def test_ctrl_n_p_cycle_highlight() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert ta._file_completion_index == 0
            await pilot.press("ctrl+n")
            assert ta._file_completion_index == 1
            await pilot.press("ctrl+p")
            assert ta._file_completion_index == 0
            await pilot.press("ctrl+p")
            assert ta._file_completion_index == 2  # wraps to the end


# --- Accept (core in-place insertion, representative vectors) --------------


def _select(ta: PromptTextArea, name: str) -> None:
    """Highlight the candidate whose project name is *name*."""
    index = next(
        i for i, c in enumerate(ta._file_completion_candidates) if c.name == name
    )
    ta._file_completion_index = index


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("+", "+sase "),
        ("+sa", "+sase "),
        ("Describe this repo. +", "Describe this repo. +sase "),
        # Accepting a project removes the other workspace target in the
        # same segment (uses `#git:foo` since `git` is a registered
        # workflow name in the test environment).
        ("#git:foo Fix bug +", "Fix bug +sase "),
        ("#git:foo +", "+sase "),
        ("Line one\n +", "Line one\n +sase "),
        (
            "---\nname: x\n---\nBody +",
            "---\nname: x\n---\nBody +sase ",
        ),
        ("%model:opus Body +", "%model:opus Body +sase "),
    ],
)
async def test_accept_applies_in_place_insertion(text: str, expected: str) -> None:
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


async def test_bof_plus_accept_inserts_tag() -> None:
    """Accepting a BOF ``+`` selection inserts the project's tag in place."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert ta._file_completion_active is True
        _select(ta, "sase")
        await pilot.press("ctrl+l")

        assert ta.text == "+sase "
        assert ta._file_completion_active is False


async def test_bare_plus_query_filters_and_accepts() -> None:
    """Typing after a BOF ``+`` filters, and accept inserts the match's tag."""
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

        assert ta.text == "+telegram "
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
            await pilot.press("+")
        _select(ta, "sase")
        await pilot.press("ctrl+l")

        assert ta.text == "+sase "
        assert ta.cursor_location == (0, len("+sase "))


async def test_accept_switches_project_within_one_segment() -> None:
    """Accepting a second project removes the first target in its segment."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo first\n---\n#git:baz second +")
        ta.cursor_location = ta._location_from_absolute(len(ta.text))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            assert ta._try_vcs_project_completion() is True
        _select(ta, "sase")
        await pilot.press("ctrl+l")

        # Only the trigger's own segment loses its other target.
        assert ta.text == "#git:foo first\n---\nsecond +sase "
        assert ta._file_completion_active is False


# --- Empty catalog & dismissal ---------------------------------------------


async def test_empty_catalog_shows_placeholder_row() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=[]):
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
            await pilot.press("+")
        await pilot.press("ctrl+l")

        assert ta.text == "+"
        assert ta._file_completion_active is False


async def test_space_after_token_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert ta._file_completion_active is True
            await pilot.press("space")

        assert ta.text == "+ "
        assert ta._file_completion_active is False


async def test_non_matching_query_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert ta._file_completion_active is True
            await pilot.press("z")  # no project starts with "z"

        assert ta.text == "+z"
        assert ta._file_completion_active is False


async def test_escape_dismisses_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("+")
            assert ta._file_completion_active is True
            await pilot.press("escape")

        assert ta._file_completion_active is False


async def test_ctrl_t_on_existing_plus_token_opens_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Review +te")
        ta.cursor_location = (0, len("Review +te"))
        with patch(_ENTRIES_PATH, return_value=_PROJECTS):
            await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == VCS_PROJECT_COMPLETION_KIND
        assert [c.name for c in ta._file_completion_candidates] == ["telegram"]
