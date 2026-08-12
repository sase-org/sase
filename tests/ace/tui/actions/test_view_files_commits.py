"""Tests for commit hints in the view-file hint flow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from sase.ace.tui.models._agent_clan_sections import ClanContextEntry, ClanContextLane
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_sections import (
    append_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec

from ._view_files_helpers import _commit_spec, _make_app


def _rendered_clan_commit_hint(
    *, diff_path: str | None = None
) -> dict[int, CommitViewSpec]:
    spec = _commit_spec(diff_path=diff_path)
    state = HeaderHintState(1, {}, None, {})
    append_context_section(
        Text(),
        (
            ClanContextLane(
                "COMMITS",
                (
                    ClanContextEntry(
                        key=spec.sha,
                        label=f"{spec.short_sha} {spec.subject}",
                        member_labels=(".one",),
                        values=(spec,),
                    ),
                ),
            ),
        ),
        level=FoldLevel.FULLY_EXPANDED,
        count_known=True,
        hint_state=state,
    )
    return state.commit_views


async def test_rendered_clan_commit_hint_opens_commit_view_modal() -> None:
    app = _make_app()
    app._hint_commit_views = _rendered_clan_commit_hint()

    await app._process_view_input("1")

    modal = app.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (app._hint_commit_views[1],)


async def test_rendered_clan_commit_hint_editor_suffix_opens_raw_diff(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "clan-commit.diff"
    app = _make_app()
    app._hint_commit_views = _rendered_clan_commit_hint(diff_path=str(diff_path))
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1@")

    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [str(diff_path)]
    assert result.open_in_editor is True


async def test_commit_hint_opens_commit_view_modal() -> None:
    app = _make_app()
    spec = _commit_spec()
    app._hint_commit_views = {1: spec}

    await app._process_view_input("1")

    app.app.push_screen.assert_called_once()
    modal = app.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (spec,)


async def test_multiple_commit_hints_open_one_navigable_commit_view_modal() -> None:
    app = _make_app()
    first = _commit_spec(sha="111111111111111111111111")
    second = _commit_spec(sha="222222222222222222222222")
    app._hint_commit_views = {1: first, 2: second}

    await app._process_view_input("2 1")

    app.app.push_screen.assert_called_once()
    modal = app.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (second, first)
    app.notify.assert_not_called()


async def test_commit_hint_copy_suffix_copies_short_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []

    def copy(content: str) -> bool:
        copied.append(content)
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        copy,
    )
    app = _make_app()
    app._hint_commit_views = {1: _commit_spec(sha="abcdef1234567890")}

    await app._process_view_input("1%")
    await asyncio.gather(*app.app._pump_free_clipboard_tasks)

    assert copied == ["abcdef123456"]
    app.notify.assert_called_once_with(
        "Copied 1 commit SHA(s)",
        severity="information",
    )
    app.app.push_screen.assert_not_called()


async def test_multiple_commit_hint_copy_suffix_copies_all_short_shas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []

    def copy(content: str) -> bool:
        copied.append(content)
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        copy,
    )
    app = _make_app()
    app._hint_commit_views = {
        1: _commit_spec(sha="111111111111111111111111"),
        2: _commit_spec(sha="222222222222222222222222"),
    }

    await app._process_view_input("1 2%")
    await asyncio.gather(*app.app._pump_free_clipboard_tasks)

    assert copied == ["111111111111 222222222222"]
    app.notify.assert_called_once_with(
        "Copied 2 commit SHA(s)",
        severity="information",
    )
    app.app.push_screen.assert_not_called()


async def test_commit_hint_editor_suffix_opens_raw_diff_path(tmp_path: Path) -> None:
    diff_path = tmp_path / "commit.diff"
    app = _make_app()
    app._hint_commit_views = {1: _commit_spec(diff_path=str(diff_path))}
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1@")

    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [str(diff_path)]
    assert result.open_in_editor is True
    app.app.push_screen.assert_not_called()


async def test_multiple_commit_hint_editor_suffix_opens_raw_diff_paths(
    tmp_path: Path,
) -> None:
    first_diff = tmp_path / "first.diff"
    third_diff = tmp_path / "third.diff"
    app = _make_app()
    app._hint_commit_views = {
        1: _commit_spec(sha="111111111111111111111111", diff_path=str(first_diff)),
        2: _commit_spec(sha="222222222222222222222222"),
        3: _commit_spec(sha="333333333333333333333333", diff_path=str(third_diff)),
    }
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1 2 3@")

    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [str(first_diff), str(third_diff)]
    assert result.open_in_editor is True
    app.notify.assert_called_once_with(
        "No raw diff path for commit(s): 222222222222",
        severity="warning",
    )
    app.app.push_screen.assert_not_called()
