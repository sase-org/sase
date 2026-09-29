"""Path-row tests for the ``:`` Command Line.

Dotfile candidates, the debounced worker boundary, and the ``--cwd`` slot.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.command_line.sources import (
    path_candidates,
    path_completion_request,
)

from tests.ace.tui.command_line._completion_sources_shared import (
    await_provider_task,
    panel,
    pin_cwd,
    shown,
    type_line,
)

pytest_plugins = ["tests.ace.tui.command_line._completion_sources_shared"]

__all__ = [
    "test_path_rows_reach_the_popup_for_a_cwd_slot_through_complete",
    "test_path_scan_lists_dotfiles_only_once_the_typed_name_starts_with_a_dot",
    "test_path_scan_runs_in_the_debounced_worker_not_on_the_keystroke",
]


def test_path_scan_lists_dotfiles_only_once_the_typed_name_starts_with_a_dot(
    tmp_path: Path,
) -> None:
    """Dotfiles stay hidden until asked for, and cache under their own key."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "src").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".cache").mkdir()

    plain = path_completion_request("", str(tmp_path))
    dotted = path_completion_request(".", str(tmp_path))
    assert [row["value"] for row in path_candidates(plain, directories_only=False)] == [
        "src/",
        "sub/",
    ]
    assert [
        row["value"] for row in path_candidates(dotted, directories_only=False)
    ] == [
        ".git/",
        "src/",
        "sub/",
        ".env",
    ]
    assert plain.source_key != dotted.source_key

    nested_plain = path_completion_request("sub/", str(tmp_path))
    nested_dotted = path_completion_request("sub/.", str(tmp_path))
    assert path_candidates(nested_plain, directories_only=False) == []
    assert [
        row["value"] for row in path_candidates(nested_dotted, directories_only=False)
    ] == ["sub/.cache/"]


async def test_path_scan_runs_in_the_debounced_worker_not_on_the_keystroke(
    grammar_handle: Any,
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The directory scan happens in a worker thread, after the debounce."""
    import sase.ace.tui.command_line.screen_completion as screen_module

    (tmp_path / "alpha").mkdir()
    (tmp_path / "notes.txt").write_text("file")
    scan_threads: list[int] = []
    real_scan = screen_module.path_candidates

    def _spy(request: Any, **kwargs: Any) -> list[dict[str, Any]]:
        scan_threads.append(threading.get_ident())
        return real_scan(request, **kwargs)

    monkeypatch.setattr(screen_module, "path_candidates", _spy)
    async with panel(grammar_handle) as (page, screen):
        pin_cwd(page, screen, tmp_path)
        await type_line(page, screen, "proc run --cwd ")
        await await_provider_task(screen)
        scan_threads.clear()

        screen._provider_cache.invalidate()
        screen._refresh_completion()  # the keystroke path: synchronous, on the loop
        assert scan_threads == []
        await await_provider_task(screen)
        assert len(scan_threads) == 1
        assert scan_threads[0] != threading.get_ident()


async def test_path_rows_reach_the_popup_for_a_cwd_slot_through_complete(
    grammar_handle: Any, history_file: Path, tmp_path: Path
) -> None:
    """``proc run --cwd `` completes directories, not files, in the pinned cwd."""
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "notes.txt").write_text("file")
    async with panel(grammar_handle) as (page, screen):
        pin_cwd(page, screen, tmp_path)
        await type_line(page, screen, "proc run --cwd ")
        await await_provider_task(screen)
        assert shown(screen) == ["alpha/", "beta/"]

        await type_line(page, screen, "proc run --cwd b")
        await await_provider_task(screen)
        assert shown(screen) == ["beta/"]
