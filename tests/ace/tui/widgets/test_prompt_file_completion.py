"""Tests for prompt input file path completion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _CompletionTestApp(App[None]):
    """Minimal app that hosts PromptInputBar for file completion tests."""

    def __init__(self, snippets: dict[str, str] | None = None) -> None:
        super().__init__()
        self._snippets: dict[str, str] = snippets or {}

    def compose(self) -> ComposeResult:
        yield PromptInputBar()


def _create_entries(root: Path) -> None:
    """Create a deterministic home tree for completion tests."""
    (root / "alpha").mkdir()
    (root / "apple").mkdir()
    (root / "docs").mkdir()
    (root / "readme.md").write_text("x", encoding="utf-8")
    (root / "results.txt").write_text("x", encoding="utf-8")


class TestPromptFileCompletion:
    async def test_detect_tilde_token_and_show_candidates(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        _create_entries(tmp_path)
        app = _CompletionTestApp()
        async with app.run_test():
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._file_completion_active is True
            assert len(ta._file_completion_candidates) > 1
            panel = bar.query_one("#prompt-completion", Static)
            assert not panel.has_class("hidden")

    async def test_single_match_directory_inserts_trailing_slash(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        app = _CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/al")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta.text == "~/alpha/"
            assert ta._file_completion_active is False

    async def test_multi_match_applies_shared_prefix_and_shows_panel(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "research").write_text("x", encoding="utf-8")
        (tmp_path / "results").write_text("x", encoding="utf-8")
        app = _CompletionTestApp()
        async with app.run_test():
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/re")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta.text == "~/res"
            assert ta._file_completion_active is True
            assert bar._completion_visible is True

    async def test_navigation_keys_update_highlight(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        _create_entries(tmp_path)
        app = _CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("tab")
                start = ta._file_completion_index
                await pilot.press("down")
                assert ta._file_completion_index != start
                await pilot.press("up")
                assert ta._file_completion_index == start

    async def test_accept_ctrl_l_inserts_selected_candidate(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "aaa.txt").write_text("x", encoding="utf-8")
        (tmp_path / "bbb.txt").write_text("x", encoding="utf-8")
        app = _CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("tab")
                await pilot.press("down")
                selected = ta._file_completion_candidates[
                    ta._file_completion_index
                ].insertion
                await pilot.press("ctrl+l")
            assert ta.text == selected
            assert ta._file_completion_active is False

    async def test_escape_dismisses_completion_panel(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        _create_entries(tmp_path)
        app = _CompletionTestApp()
        async with app.run_test() as pilot:
            bar = app.query_one(PromptInputBar)
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("tab")
                assert ta._file_completion_active is True
                await pilot.press("escape")
            assert ta._file_completion_active is False
            assert bar._completion_visible is False
            assert ta._vim_mode == "insert"

    async def test_non_path_tab_still_expands_snippet(self) -> None:
        app = _CompletionTestApp(snippets={"foo": "BAR"})
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("foo")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("tab")
            assert ta.text == "BAR"

    async def test_completion_state_resets_on_submit_and_cancel(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        _create_entries(tmp_path)
        app = _CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("tab")
                assert ta._file_completion_active is True
                ta.action_submit_prompt()
                assert ta._file_completion_active is False

                ta.load_text("~/")
                ta.cursor_location = (0, 2)
                await pilot.press("tab")
                assert ta._file_completion_active is True
                await pilot.press("ctrl+c")
            assert ta._file_completion_active is False
