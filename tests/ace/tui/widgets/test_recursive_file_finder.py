"""Tests for the recursive fuzzy file finder pure logic (Ctrl+R)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from _pytest.monkeypatch import MonkeyPatch

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets import recursive_file_finder as rff
from sase.ace.tui.widgets.recursive_file_finder import (
    FinderModel,
    derive_root_from_path,
    enumerate_recursive_candidates,
    _fuzzy_match,
    _rank_candidates,
    resolve_root_abs,
    split_root_and_query,
)


def _candidate(display: str, is_dir: bool = False) -> CompletionCandidate:
    return CompletionCandidate(
        display=display,
        insertion=display,
        is_dir=is_dir,
        name=display.rstrip("/").rsplit("/", 1)[-1],
    )


class TestFuzzyMatch:
    def test_subsequence_match_returns_runs(self) -> None:
        match = _fuzzy_match("ace", "src/ace/x.py")
        assert match is not None
        assert match.runs == ((4, 7),)

    def test_case_insensitive(self) -> None:
        assert _fuzzy_match("ACE", "src/ace/x.py") is not None
        assert _fuzzy_match("ace", "SRC/ACE/X.PY") is not None

    def test_non_subsequence_returns_none(self) -> None:
        assert _fuzzy_match("zzz", "abcabc") is None
        # Out of order is not a subsequence.
        assert _fuzzy_match("cba", "abc") is None

    def test_empty_query_matches_with_zero_score(self) -> None:
        match = _fuzzy_match("", "anything/at/all.py")
        assert match is not None
        assert match.score == 0
        assert match.runs == ()

    def test_consecutive_run_scores_higher_than_scattered(self) -> None:
        consecutive = _fuzzy_match("abc", "abcxx")
        scattered = _fuzzy_match("abc", "axbxc")
        assert consecutive is not None and scattered is not None
        assert consecutive.score > scattered.score

    def test_boundary_match_scores_higher(self) -> None:
        boundary = _fuzzy_match("fb", "foo_bar")
        mid_word = _fuzzy_match("fb", "foobar")
        assert boundary is not None and mid_word is not None
        assert boundary.score > mid_word.score

    def test_camelcase_counts_as_boundary(self) -> None:
        camel = _fuzzy_match("fb", "fooBar")
        flat = _fuzzy_match("fb", "foobar")
        assert camel is not None and flat is not None
        assert camel.score > flat.score


class TestRankCandidates:
    def test_literal_prefix_outranks_basename_prefix(self) -> None:
        candidates = [
            _candidate("test/foo.py"),
            _candidate("foo/test.py"),
        ]
        ranked = _rank_candidates("test", candidates)
        assert [c.display for c, _ in ranked][0] == "test/foo.py"

    def test_non_matches_filtered_out(self) -> None:
        candidates = [_candidate("alpha.py"), _candidate("beta.py")]
        ranked = _rank_candidates("alpha", candidates)
        assert [c.display for c, _ in ranked] == ["alpha.py"]

    def test_empty_query_returns_all_shallow_first(self) -> None:
        candidates = [
            _candidate("a/b/c/deep.py"),
            _candidate("top.py"),
            _candidate("a/mid.py"),
        ]
        ranked = _rank_candidates("", candidates)
        assert [c.display for c, _ in ranked] == [
            "top.py",
            "a/mid.py",
            "a/b/c/deep.py",
        ]

    def test_ties_broken_by_length_then_lexicographic(self) -> None:
        candidates = [_candidate("abcdef.py"), _candidate("abc.py")]
        ranked = _rank_candidates("abc", candidates)
        # Same prefix-quality match, shorter path wins the tie-break.
        assert [c.display for c, _ in ranked][0] == "abc.py"


class TestFinderModel:
    def test_initial_state_ranks_all(self) -> None:
        model = FinderModel([_candidate("a.py"), _candidate("b.py")])
        assert model.match_count == 2
        assert model.total == 2
        assert model.index == 0

    def test_set_query_filters_and_resets_index(self) -> None:
        model = FinderModel(
            [_candidate("alpha.py"), _candidate("beta.py"), _candidate("gamma.py")]
        )
        model.move(2)
        assert model.index == 2
        model.set_query("beta")
        assert model.match_count == 1
        assert model.index == 0
        assert model.selected is not None
        assert model.selected.display == "beta.py"

    def test_move_wraps_around(self) -> None:
        model = FinderModel([_candidate("a.py"), _candidate("b.py")])
        model.move(-1)
        assert model.index == 1
        model.move(1)
        assert model.index == 0

    def test_selected_none_when_no_matches(self) -> None:
        model = FinderModel([_candidate("alpha.py")])
        model.set_query("zzzzz")
        assert model.match_count == 0
        assert model.selected is None


class TestRootResolution:
    def test_derive_root_from_directory(self) -> None:
        assert derive_root_from_path("src/foo/", True) == "src/foo/"
        assert derive_root_from_path("src/foo", True) == "src/foo/"

    def test_derive_root_from_file(self) -> None:
        assert derive_root_from_path("src/foo.py", False) == "src/"
        assert derive_root_from_path("foo.py", False) == ""

    def test_derive_root_preserves_at_prefix(self) -> None:
        assert derive_root_from_path("@src/foo.py", False) == "@src/"

    def test_split_root_and_query(self) -> None:
        assert split_root_and_query("src/foo") == ("src/", "foo")
        assert split_root_and_query("foo") == ("", "foo")
        assert split_root_and_query("@src/foo") == ("@src/", "foo")

    def test_resolve_root_abs(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert resolve_root_abs("") == os.getcwd()
        assert resolve_root_abs("src/") == os.path.abspath("src")
        assert resolve_root_abs("@src/") == os.path.abspath("src")

    def test_resolve_root_abs_uses_base_dir_for_relative_root(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        project_root = tmp_path / "project"
        other_cwd = tmp_path / "cwd"
        (project_root / "sdd").mkdir(parents=True)
        other_cwd.mkdir()
        monkeypatch.chdir(other_cwd)

        assert resolve_root_abs("sdd/", base_dir=project_root) == str(
            project_root / "sdd"
        )


class TestEnumerate:
    def test_walk_excludes_heavy_and_dot_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "pkg" / "sub").mkdir(parents=True)
        (tmp_path / "node_modules" / "x").mkdir(parents=True)
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "pkg" / "sub" / "deep.py").write_text("x", encoding="utf-8")
        (tmp_path / "top.txt").write_text("x", encoding="utf-8")
        (tmp_path / "node_modules" / "x" / "junk.js").write_text("x", encoding="utf-8")
        (tmp_path / ".hidden" / "secret").write_text("x", encoding="utf-8")

        candidates, truncated = enumerate_recursive_candidates(str(tmp_path), "")
        displays = {c.display for c in candidates}

        assert truncated is False
        assert "top.txt" in displays
        assert "pkg/sub/deep.py" in displays
        # Derived intermediate directories appear with a trailing slash.
        assert "pkg/" in displays
        assert "pkg/sub/" in displays
        assert not any("node_modules" in d for d in displays)
        assert not any(".hidden" in d for d in displays)

    def test_display_prefixed_with_root_display(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b.py").write_text("x", encoding="utf-8")
        candidates, _ = enumerate_recursive_candidates(str(tmp_path), "src/")
        displays = {c.display for c in candidates}
        assert "src/a/b.py" in displays
        assert "src/a/" in displays
        # display and insertion match for the recursive finder.
        for c in candidates:
            assert c.display == c.insertion

    def test_git_mode_respects_gitignore(self, tmp_path: Path) -> None:
        _git(tmp_path, "init")
        (tmp_path / "keep.py").write_text("x", encoding="utf-8")
        (tmp_path / "ignored.log").write_text("x", encoding="utf-8")
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("x", encoding="utf-8")
        (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")

        candidates, _ = enumerate_recursive_candidates(str(tmp_path), "")
        displays = {c.display for c in candidates}

        # Tracked + untracked-not-ignored show up; ignored files do not.
        assert "keep.py" in displays
        assert "pkg/mod.py" in displays
        assert "pkg/" in displays
        assert ".gitignore" in displays
        assert "ignored.log" not in displays

    def test_truncation_flagged_when_cap_exceeded(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rff, "MAX_RESULTS", 3)
        for i in range(10):
            (tmp_path / f"file_{i}.py").write_text("x", encoding="utf-8")
        candidates, truncated = enumerate_recursive_candidates(str(tmp_path), "")
        assert truncated is True
        # File candidates are capped to MAX_RESULTS (dirs derived on top).
        files = [c for c in candidates if not c.is_dir]
        assert len(files) == 3


def _git(cwd: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
