"""Tests for warm prompt path inventory snapshots."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import os

from sase.ace.tui.widgets.prompt_path_inventory import (
    MAX_PROMPT_PATH_ROWS,
    PromptPathRow,
    load_prompt_path_snapshot,
    prompt_path_directory_key,
    revalidate_prompt_path_snapshot,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def test_snapshot_keeps_dotfiles_and_sorts_directories_first(tmp_path: Path) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / ".hidden-dir").mkdir()
    (tmp_path / "Alpha.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")

    snapshot = load_prompt_path_snapshot(str(tmp_path))

    assert snapshot.directory_key == str(tmp_path)
    assert snapshot.token is not None
    assert snapshot.rows == (
        PromptPathRow(".hidden-dir", True),
        PromptPathRow("zeta", True),
        PromptPathRow(".hidden", False),
        PromptPathRow("Alpha.txt", False),
    )


def test_snapshot_caps_directory_entries(tmp_path: Path) -> None:
    for index in range(MAX_PROMPT_PATH_ROWS + 5):
        (tmp_path / f"entry-{index:04}").touch()

    snapshot = load_prompt_path_snapshot(str(tmp_path))

    assert len(snapshot.rows) == MAX_PROMPT_PATH_ROWS


def test_unreadable_directory_returns_cold_empty_snapshot(tmp_path: Path) -> None:
    with patch(
        "sase.ace.tui.widgets.prompt_path_inventory.os.scandir",
        side_effect=OSError("unreadable"),
    ):
        snapshot = load_prompt_path_snapshot(str(tmp_path))

    assert snapshot.rows == ()
    assert snapshot.token is None


def test_revalidation_skips_scan_when_directory_token_is_unchanged(
    tmp_path: Path,
) -> None:
    (tmp_path / "one.txt").touch()
    previous = load_prompt_path_snapshot(str(tmp_path))

    with patch(
        "sase.ace.tui.widgets.prompt_path_inventory.os.scandir",
        side_effect=AssertionError("unchanged directory was rescanned"),
    ):
        current = revalidate_prompt_path_snapshot(str(tmp_path), previous)

    assert current is previous


def test_directory_key_matches_prompt_file_expansion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROMPT_PATH_CHILD", "src")

    assert prompt_path_directory_key("", "$PROMPT_PATH_CHILD/") == str(tmp_path / "src")


def test_cold_snapshot_schedules_one_threaded_worker(tmp_path: Path) -> None:
    text_area = PromptTextArea()
    text_area._prompt_path_snapshots = {}
    text_area._prompt_path_inflight = set()
    text_area._prompt_path_completion_directory_key = None

    with (
        patch(
            "sase.ace.tui.widgets._file_completion_base.prompt_path_directory_key",
            return_value=str(tmp_path),
        ),
        patch.object(type(text_area), "run_worker") as run_worker,
    ):
        assert text_area._open_prompt_path_directory("") is None
        assert text_area._open_prompt_path_directory("") is None

    assert text_area._prompt_path_completion_directory_key == str(tmp_path)
    assert text_area._prompt_path_inflight == {str(tmp_path)}
    run_worker.assert_called_once()
    assert run_worker.call_args.kwargs["group"] == "prompt-path-inventory"
    assert run_worker.call_args.kwargs["thread"] is True


async def test_at_keystroke_does_not_stat_or_scan() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        fail = AssertionError("keystroke path touched the filesystem")

        with (
            patch.object(os, "stat", side_effect=fail),
            patch.object(os, "scandir", side_effect=fail),
        ):
            await pilot.press("@")

        assert text_area.text == "@"
