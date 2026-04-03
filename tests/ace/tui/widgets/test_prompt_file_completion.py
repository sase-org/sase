"""Tests for prompt input file path completion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    build_completion_candidates,
    extract_token_around_cursor,
    is_path_like_token,
)
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
                await pilot.press("ctrl+f")
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
                await pilot.press("ctrl+f")
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
                await pilot.press("ctrl+f")
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
                await pilot.press("ctrl+f")
                assert ta._file_completion_active is True
                ta.action_submit_prompt()
                assert ta._file_completion_active is False

                ta.load_text("~/")
                ta.cursor_location = (0, 2)
                await pilot.press("ctrl+f")
                assert ta._file_completion_active is True
                await pilot.press("ctrl+c")
            assert ta._file_completion_active is False

    async def test_dotfiles_hidden_by_default(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".hidden_dir").mkdir()
        (tmp_path / ".hidden_file").write_text("x", encoding="utf-8")
        (tmp_path / "visible_dir").mkdir()
        (tmp_path / "visible_file").write_text("x", encoding="utf-8")
        app = _CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            names = [c.name for c in ta._file_completion_candidates]
            assert ".hidden_dir" not in names
            assert ".hidden_file" not in names
            assert "visible_dir" in names
            assert "visible_file" in names

    async def test_dotfiles_shown_when_prefix_starts_with_dot(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".config").mkdir()
        (tmp_path / ".bashrc").write_text("x", encoding="utf-8")
        (tmp_path / "visible").mkdir()
        app = _CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/.")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            names = [c.name for c in ta._file_completion_candidates]
            assert ".config" in names
            assert ".bashrc" in names
            assert "visible" not in names

    async def test_directory_drilldown_on_accept(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        (tmp_path / "alpha" / "foo.py").write_text("x", encoding="utf-8")
        (tmp_path / "alpha" / "bar.py").write_text("x", encoding="utf-8")
        app = _CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+f")
                assert ta._file_completion_active is True
                # First candidate should be alpha/ (dirs first, alphabetical)
                assert ta._file_completion_candidates[0].name == "alpha"
                # Accept the directory via Ctrl+L
                await pilot.press("ctrl+l")
                # Should have drilled down into alpha/
                assert ta.text == "~/alpha/"
                assert ta._file_completion_active is True
                names = [c.name for c in ta._file_completion_candidates]
                assert "foo.py" in names
                assert "bar.py" in names

    async def test_enter_accepts_completion_instead_of_submitting(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "aaa.txt").write_text("x", encoding="utf-8")
        (tmp_path / "bbb.txt").write_text("x", encoding="utf-8")
        app = _CompletionTestApp()
        submitted = False
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            original_submit = ta.action_submit_prompt

            def _track_submit() -> None:
                nonlocal submitted
                submitted = True
                original_submit()

            ta.action_submit_prompt = _track_submit  # type: ignore[assignment]
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+f")
                assert ta._file_completion_active is True
                await pilot.press("down")
                selected = ta._file_completion_candidates[
                    ta._file_completion_index
                ].insertion
                await pilot.press("enter")
            # The selected candidate was inserted
            assert ta.text == selected
            # Completion menu was dismissed
            assert ta._file_completion_active is False
            # No submit was triggered
            assert submitted is False

    async def test_symlink_directories_followed(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        (real_dir / "inside.txt").write_text("x", encoding="utf-8")
        link = tmp_path / "link_dir"
        link.symlink_to(real_dir)
        app = _CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("~/")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            candidates_by_name = {c.name: c for c in ta._file_completion_candidates}
            assert "real_dir" in candidates_by_name
            assert "link_dir" in candidates_by_name
            assert candidates_by_name["real_dir"].is_dir is True
            assert candidates_by_name["link_dir"].is_dir is True
            assert candidates_by_name["link_dir"].display == "link_dir/"


class TestFileCompletionModule:
    """Tests for the extracted file_completion module functions."""

    def test_is_path_like_token(self) -> None:
        assert is_path_like_token("~/") is True
        assert is_path_like_token("/tmp/") is True
        assert is_path_like_token("./src/") is True
        assert is_path_like_token("../") is True
        assert is_path_like_token(".sase/") is True
        assert is_path_like_token("docs/readme") is True
        assert is_path_like_token("hello") is False
        assert is_path_like_token("") is False
        # @-prefixed paths
        assert is_path_like_token("@~/") is True
        assert is_path_like_token("@/tmp/") is True
        assert is_path_like_token("@./src/") is True
        assert is_path_like_token("@../") is True
        assert is_path_like_token("@.sase/") is True
        assert is_path_like_token("@docs/readme") is True
        assert is_path_like_token("@hello") is False
        assert is_path_like_token("@") is False

    def test_extract_token_around_cursor(self) -> None:
        assert extract_token_around_cursor("hello world", 3) == (0, 5, "hello")
        assert extract_token_around_cursor("hello world", 8) == (6, 11, "world")
        assert extract_token_around_cursor("  ", 1) is None
        assert extract_token_around_cursor("~/foo", 5) == (0, 5, "~/foo")

    def test_build_completion_candidates_dotfile_filtering(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        candidates, _ = build_completion_candidates("~/")
        names = [c.name for c in candidates]
        assert "visible" in names
        assert ".hidden" not in names

        # With dot prefix, dotfiles are shown
        candidates, _ = build_completion_candidates("~/.")
        names = [c.name for c in candidates]
        assert ".hidden" in names

    def test_build_completion_candidates_follow_symlinks(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "link").symlink_to(real)
        candidates, _ = build_completion_candidates("~/")
        by_name = {c.name: c for c in candidates}
        assert by_name["link"].is_dir is True
        assert by_name["link"].display == "link/"

    def test_build_completion_candidates_at_prefix(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        _create_entries(tmp_path)
        candidates, _ = build_completion_candidates("@~/")
        assert len(candidates) > 1
        for c in candidates:
            assert c.insertion.startswith("@~/")

    def test_build_completion_candidates_at_prefix_partial(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        candidates, _ = build_completion_candidates("@~/al")
        assert len(candidates) == 1
        assert candidates[0].name == "alpha"
        assert candidates[0].insertion == "@~/alpha/"


class TestAtPrefixIntegration:
    """Integration tests for @-prefixed file completion in the widget."""

    async def test_at_tilde_triggers_completion(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        _create_entries(tmp_path)
        app = _CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("@~/")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta._file_completion_active is True
            assert len(ta._file_completion_candidates) > 1
            for c in ta._file_completion_candidates:
                assert c.insertion.startswith("@~/")

    async def test_at_single_match_inserts_with_prefix(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        app = _CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("@~/al")
            ta.cursor_location = (0, 5)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            assert ta.text == "@~/alpha/"
            assert ta._file_completion_active is False

    async def test_at_prefix_directory_drilldown(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        (tmp_path / "alpha" / "foo.py").write_text("x", encoding="utf-8")
        (tmp_path / "alpha" / "bar.py").write_text("x", encoding="utf-8")
        app = _CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("@~/")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+f")
                assert ta._file_completion_active is True
                # First candidate should be alpha/ (dirs first, alphabetical)
                assert ta._file_completion_candidates[0].name == "alpha"
                # Accept the directory via Ctrl+L to drill down
                await pilot.press("ctrl+l")
                assert ta.text == "@~/alpha/"
                assert ta._file_completion_active is True
                names = [c.name for c in ta._file_completion_candidates]
                assert "foo.py" in names
                assert "bar.py" in names
                for c in ta._file_completion_candidates:
                    assert c.insertion.startswith("@~/alpha/")
