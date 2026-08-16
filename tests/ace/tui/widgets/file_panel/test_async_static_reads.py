"""Tests for off-thread static file/diff reads in AgentFilePanel.

The Textual event loop must not perform the disk read for saved static
files, saved static diffs, or precomputed agent diffs reached through the
file panel's static path. These tests pin that contract:

- ``display_static_file``/``display_static_diff`` schedule a thread worker
  and return without opening the file on the calling thread.
- Stale results from superseded reads are dropped before they can paint
  over a newer selection.
- Render helpers handle the success/empty/missing terminal states.
"""

from __future__ import annotations

import builtins
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.widgets.file_panel import AgentFilePanel
from sase.ace.tui.widgets.file_panel._display import (
    StaticReadResult,
    _read_static_file,
)
from sase.ace.tui.widgets.file_panel._messages import linked_slot_id


def _make_render_panel() -> MagicMock:
    """Build a MagicMock pre-wired with the bits the static helpers need."""
    panel = MagicMock()
    panel.post_message = MagicMock()
    panel._has_displayed_content = False
    panel._file_list = []
    panel._current_file_index = 0
    panel._total_line_count = 0
    panel._visible_line_count = 0
    panel._is_content_capped = False
    panel._full_content = None
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._content_fetched_at = None
    panel._static_header_path = None
    panel._static_request_id = 0
    panel._static_worker = None

    panel._post_file_visibility = types.MethodType(
        AgentFilePanel._post_file_visibility, panel
    )
    panel._consume_image_cleanup_segments = types.MethodType(
        AgentFilePanel._consume_image_cleanup_segments, panel
    )
    panel._count_lines = types.MethodType(AgentFilePanel._count_lines, panel)
    panel._timestamp_header = types.MethodType(AgentFilePanel._timestamp_header, panel)
    panel._render_full_content = types.MethodType(
        AgentFilePanel._render_full_content, panel
    )
    panel._post_line_count_changed = MagicMock()
    from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache

    panel._content_render_cache = LazySyntaxRenderCache(max_entries=2)
    panel._update_body = types.MethodType(AgentFilePanel._update_body, panel)
    panel._cancel_static_worker = types.MethodType(
        AgentFilePanel._cancel_static_worker, panel
    )
    panel._schedule_static_read = types.MethodType(
        AgentFilePanel._schedule_static_read, panel
    )
    panel._handle_static_read_result = types.MethodType(
        AgentFilePanel._handle_static_read_result, panel
    )
    panel._render_static_file_result = types.MethodType(
        AgentFilePanel._render_static_file_result, panel
    )
    panel._render_static_diff_result = types.MethodType(
        AgentFilePanel._render_static_diff_result, panel
    )
    panel._display_static_image = MagicMock()
    return panel


def test_display_static_file_schedules_thread_worker_without_reading(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """display_static_file must hand the read off to a thread worker.

    The Textual event loop should not call ``open()`` or read disk during
    the call; it should only schedule and return.
    """
    target = tmp_path / "notes.txt"
    target.write_text("hello world\n")

    panel = _make_render_panel()
    scheduled: list[Any] = []

    def fake_run_worker(task: Any, **kwargs: Any) -> Any:
        scheduled.append((task, kwargs))
        return MagicMock(is_running=True)

    panel.run_worker = fake_run_worker

    real_open = builtins.open

    def forbidden_open(*args: Any, **kwargs: Any) -> Any:
        # Allow opens unrelated to our target — but the panel must not
        # touch the target on the UI thread.
        if args and str(args[0]) == str(target):
            raise AssertionError(
                "display_static_file opened the file on the calling thread"
            )
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", forbidden_open)

    AgentFilePanel.display_static_file(panel, str(target))

    assert len(scheduled) == 1
    _, kwargs = scheduled[0]
    assert kwargs == {"thread": True}
    assert panel._static_request_id == 1
    assert panel._static_worker is not None


def test_display_static_diff_schedules_thread_worker_without_reading(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """display_static_diff routes through the same thread-worker path."""
    target = tmp_path / "saved.diff"
    target.write_text("--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n")

    panel = _make_render_panel()
    scheduled: list[Any] = []

    def fake_run_worker(task: Any, **kwargs: Any) -> Any:
        scheduled.append((task, kwargs))
        return MagicMock(is_running=True)

    panel.run_worker = fake_run_worker

    real_open = builtins.open

    def forbidden_open(*args: Any, **kwargs: Any) -> Any:
        if args and str(args[0]) == str(target):
            raise AssertionError(
                "display_static_diff opened the file on the calling thread"
            )
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", forbidden_open)

    AgentFilePanel.display_static_diff(panel, str(target))

    assert len(scheduled) == 1
    _, kwargs = scheduled[0]
    assert kwargs == {"thread": True}


def test_display_static_file_cancels_prior_worker_on_resched(tmp_path: Path) -> None:
    """A second display_static_file must cancel the in-flight first worker."""
    panel = _make_render_panel()
    workers: list[MagicMock] = []

    def fake_run_worker(_task: Any, **_kwargs: Any) -> Any:
        w = MagicMock(is_running=True)
        workers.append(w)
        return w

    panel.run_worker = fake_run_worker

    a = tmp_path / "a.txt"
    a.write_text("a")
    b = tmp_path / "b.txt"
    b.write_text("b")

    AgentFilePanel.display_static_file(panel, str(a))
    AgentFilePanel.display_static_file(panel, str(b))

    assert len(workers) == 2
    workers[0].cancel.assert_called_once()
    assert panel._static_worker is workers[1]
    assert panel._static_request_id == 2


def test_handle_static_read_result_drops_stale_request_id(tmp_path: Path) -> None:
    """A result from a superseded request_id must not paint."""
    panel = _make_render_panel()
    panel._static_request_id = 5  # current

    stale = StaticReadResult(
        request_id=3,
        mode="file",
        path=str(tmp_path / "old.txt"),
        expanded_path=str(tmp_path / "old.txt"),
        status="ok",
        content="stale",
        lexer="text",
    )

    AgentFilePanel._handle_static_read_result(panel, stale)

    panel.update.assert_not_called()
    panel.post_message.assert_not_called()


def test_handle_static_read_result_drops_when_path_no_longer_current(
    tmp_path: Path,
) -> None:
    """If the user moved off the file before its read completed, drop it."""
    panel = _make_render_panel()
    panel._static_request_id = 1
    # User has navigated to file B; the result we receive is for file A.
    panel._file_list = [str(tmp_path / "b.txt")]
    panel._current_file_index = 0

    result = StaticReadResult(
        request_id=1,
        mode="file",
        path=str(tmp_path / "a.txt"),
        expanded_path=str(tmp_path / "a.txt"),
        status="ok",
        content="from a",
        lexer="text",
    )

    AgentFilePanel._handle_static_read_result(panel, result)

    panel.update.assert_not_called()


def test_handle_static_read_result_drops_when_current_is_live_diff(
    tmp_path: Path,
) -> None:
    """If the live-diff sentinel is selected, a static result must not paint."""
    panel = _make_render_panel()
    panel._static_request_id = 1
    panel._file_list = ["__live_diff__"]
    panel._current_file_index = 0

    result = StaticReadResult(
        request_id=1,
        mode="file",
        path=str(tmp_path / "a.txt"),
        expanded_path=str(tmp_path / "a.txt"),
        status="ok",
        content="x",
        lexer="text",
    )

    AgentFilePanel._handle_static_read_result(panel, result)

    panel.update.assert_not_called()


def test_handle_static_read_result_drops_when_current_is_linked_diff(
    tmp_path: Path,
) -> None:
    """If a linked diff slot is selected, a static result must not paint."""
    panel = _make_render_panel()
    panel._static_request_id = 1
    panel._file_list = [linked_slot_id("sase-core")]
    panel._current_file_index = 0

    result = StaticReadResult(
        request_id=1,
        mode="file",
        path=str(tmp_path / "a.txt"),
        expanded_path=str(tmp_path / "a.txt"),
        status="ok",
        content="x",
        lexer="text",
    )

    AgentFilePanel._handle_static_read_result(panel, result)

    panel.update.assert_not_called()


def test_handle_static_read_result_renders_diff_success(tmp_path: Path) -> None:
    """A successful diff result routes to the diff render helper."""
    panel = _make_render_panel()
    panel._static_request_id = 1

    result = StaticReadResult(
        request_id=1,
        mode="diff",
        path=str(tmp_path / "saved.diff"),
        expanded_path=str(tmp_path / "saved.diff"),
        status="ok",
        content="--- a\n+++ b\n@@\n-x\n+y\n",
        lexer="diff",
    )

    AgentFilePanel._handle_static_read_result(panel, result)

    assert panel.update.called
    assert panel._content_mode == "static_diff"
    assert panel.post_message.call_args[0][0].has_file is True


def test_render_static_diff_result_handles_empty(tmp_path: Path) -> None:
    """Empty saved diffs post has_file=False with the diff-specific message."""
    panel = _make_render_panel()
    result = StaticReadResult(
        request_id=1,
        mode="diff",
        path=str(tmp_path / "empty.diff"),
        expanded_path=str(tmp_path / "empty.diff"),
        status="empty",
    )

    AgentFilePanel._render_static_diff_result(panel, result)

    assert panel.post_message.call_args[0][0].has_file is False


def test_render_static_diff_result_handles_missing(tmp_path: Path) -> None:
    """Missing saved diffs post has_file=False."""
    panel = _make_render_panel()
    result = StaticReadResult(
        request_id=1,
        mode="diff",
        path=str(tmp_path / "missing.diff"),
        expanded_path=str(tmp_path / "missing.diff"),
        status="missing",
    )

    AgentFilePanel._render_static_diff_result(panel, result)

    assert panel.post_message.call_args[0][0].has_file is False


def test_read_static_file_returns_image_status_for_image_paths(
    tmp_path: Path,
) -> None:
    """The worker must short-circuit on image paths so it does not read bytes."""
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n\xff")

    result = _read_static_file(7, str(img), mode="file")

    assert result.status == "image"
    assert result.request_id == 7
    assert result.content is None


def test_read_static_file_classifies_missing(tmp_path: Path) -> None:
    """Missing files surface as status='missing' with no content."""
    target = tmp_path / "nope.txt"

    result = _read_static_file(1, str(target), mode="file")

    assert result.status == "missing"
    assert result.content is None


def test_read_static_file_classifies_empty(tmp_path: Path) -> None:
    """Whitespace-only files surface as status='empty'."""
    target = tmp_path / "blank.txt"
    target.write_text("   \n")

    result = _read_static_file(1, str(target), mode="file")

    assert result.status == "empty"


def test_read_static_file_picks_lexer_from_extension(tmp_path: Path) -> None:
    """The worker computes the lexer from the path extension."""
    target = tmp_path / "module.py"
    target.write_text("def f():\n    return 1\n")

    result = _read_static_file(1, str(target), mode="file")

    assert result.status == "ok"
    assert result.lexer == "python"
    assert result.content == "def f():\n    return 1\n"


def test_read_static_file_diff_mode_pins_diff_lexer(tmp_path: Path) -> None:
    """Diff mode always uses the 'diff' lexer regardless of extension."""
    target = tmp_path / "saved.txt"
    target.write_text("--- a\n+++ b\n")

    result = _read_static_file(1, str(target), mode="diff")

    assert result.status == "ok"
    assert result.lexer == "diff"
