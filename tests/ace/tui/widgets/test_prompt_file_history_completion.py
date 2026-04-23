"""Tests for Ctrl+T file-reference history completion in the prompt input."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


class TestFileHistoryCompletion:
    """Ctrl+T at an empty cursor prefix shows file-reference history."""

    async def test_empty_prompt_with_history_shows_panel(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts", "~/notes/ideas.md"])

        app = CompletionTestApp()
        async with app.run_test():
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.cursor_location = (0, 0)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._file_completion_active is True
            assert ta._completion_kind == "file_history"
            names = [c.insertion for c in ta._file_completion_candidates]
            # Last recorded comes first.
            assert names == ["~/notes/ideas.md", "/etc/hosts"]
            panel = bar.query_one("#prompt-completion", Static)
            assert not panel.has_class("hidden")
            assert panel.border_title == "recent files"

    async def test_empty_prompt_with_empty_history_is_noop(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        app = CompletionTestApp()
        async with app.run_test():
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.cursor_location = (0, 0)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._file_completion_active is False
            panel = bar.query_one("#prompt-completion", Static)
            assert panel.has_class("hidden")

    async def test_whitespace_prefix_triggers_history(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts"])

        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("   ")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._completion_kind == "file_history"
            assert ta._file_completion_active is True

    async def test_trailing_space_at_end_of_line_triggers_history(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts"])

        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("look at ")
            ta.cursor_location = (0, 8)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._completion_kind == "file_history"
            assert ta._file_completion_active is True

    async def test_cursor_between_two_spaces_triggers_history(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts"])

        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("foo  bar")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._completion_kind == "file_history"
            assert ta._file_completion_active is True

    async def test_cursor_on_plain_word_still_clears(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts"])

        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("hello")
            ta.cursor_location = (0, 5)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                ta._try_file_completion_tab()
            assert ta._file_completion_active is False

    async def test_history_panel_survives_cursor_move_within_whitespace(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts"])

        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("foo   bar")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
                assert ta._completion_kind == "file_history"
                ta.cursor_location = (0, 5)
                ta._refresh_file_completion_from_cursor()
            assert ta._file_completion_active is True
            assert ta._completion_kind == "file_history"

    async def test_accept_inserts_path_at_cursor(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts"])

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.cursor_location = (0, 0)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                assert ta._file_completion_active is True
                await pilot.press("ctrl+l")
            assert ta.text == "/etc/hosts"
            assert ta._file_completion_active is False
            assert ta.cursor_location == (0, len("/etc/hosts"))

    async def test_path_token_still_uses_file_completion(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        (tmp_path / "alpha").mkdir()
        (tmp_path / "apple").mkdir()
        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._completion_kind == "file"

    async def test_ctrl_d_removes_highlighted_entry_and_keeps_panel_open(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import (
            load_file_references,
            record_file_references,
        )

        record_file_references(["/a", "/b", "/c"])
        # Most-recent first on disk: ["/c", "/b", "/a"]

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.cursor_location = (0, 0)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                assert ta._file_completion_active is True
                # Select the middle entry ("/b")
                await pilot.press("ctrl+n")
                assert (
                    ta._file_completion_candidates[ta._file_completion_index].insertion
                    == "/b"
                )
                await pilot.press("ctrl+d")
            # Panel stays open with the remaining entries.
            assert ta._file_completion_active is True
            assert ta._completion_kind == "file_history"
            insertions = [c.insertion for c in ta._file_completion_candidates]
            assert insertions == ["/c", "/a"]
            # Clamped selection — original idx was 1; new length is 2, so idx stays 1.
            assert ta._file_completion_index == 1
            # Deletion persisted to disk.
            assert load_file_references() == ["/c", "/a"]

    async def test_ctrl_d_on_last_remaining_entry_closes_panel(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import (
            load_file_references,
            record_file_references,
        )

        record_file_references(["/only"])

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.cursor_location = (0, 0)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                assert ta._file_completion_active is True
                await pilot.press("ctrl+d")
            assert ta._file_completion_active is False
            assert bar._completion_visible is False
            assert load_file_references() == []

    async def test_ctrl_d_is_passthrough_for_file_kind(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        (tmp_path / "alpha").mkdir()
        (tmp_path / "apple").mkdir()

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                assert ta._completion_kind == "file"
                assert ta._file_completion_active is True
                insertions_before = {
                    c.insertion for c in ta._file_completion_candidates
                }
                await pilot.press("ctrl+d")
            # Ctrl+D was not swallowed by our history-delete handler: both
            # candidates are still present (neither ~/alpha/ nor ~/apple/
            # has been stripped from the list).
            insertions_after = {c.insertion for c in ta._file_completion_candidates}
            assert insertions_before.issubset(
                insertions_after
            ) or insertions_after.issubset(insertions_before)
            # Most importantly, no history file was written by a stray delete.
            assert not (tmp_path / "hist.json").exists()

    async def test_typing_after_history_trigger_dismisses_panel(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sase.history.file_references._HISTORY_FILE",
            tmp_path / "hist.json",
        )
        from sase.history.file_references import record_file_references

        record_file_references(["/etc/hosts", "~/a.md"])

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("")
            ta.cursor_location = (0, 0)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                assert ta._file_completion_active is True
                await pilot.press("x")
            assert ta._file_completion_active is False
