"""Unit tests for the sase.ace.tui.widgets.file_completion module."""

from __future__ import annotations

from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from sase.ace.tui.widgets.file_completion import (
    build_completion_candidates,
    extract_token_around_cursor,
    is_path_like_token,
)

from ._completion_helpers import create_entries


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

    def test_extract_token_stops_at_special_characters(self) -> None:
        # Cursor between ~/foo and ? — should extract ~/foo, not ~/foo?
        assert extract_token_around_cursor("~/foo?", 5) == (0, 5, "~/foo")
        # Colon delimiter: "check: ~/Downloads" with cursor at end
        assert extract_token_around_cursor("check: ~/Downloads", 18) == (
            7,
            18,
            "~/Downloads",
        )
        # Parentheses: "(~/src/)" with cursor just after the closing /
        assert extract_token_around_cursor("(~/src/)", 7) == (1, 7, "~/src/")
        # Pipe delimiter
        assert extract_token_around_cursor("~/a|~/b", 3) == (0, 3, "~/a")
        assert extract_token_around_cursor("~/a|~/b", 4) == (4, 7, "~/b")

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
        create_entries(tmp_path)
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
