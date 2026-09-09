"""Tests for resolving file-path links from pager context."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.pager.resolve import resolve_link, resolve_ref

from ._resolve_helpers import _context, _write


def test_resolve_ref_finds_a_relative_path_in_a_later_anchor(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "src" / "foo.py")

    target = resolve_ref("src/foo.py", context=_context(first, second))

    assert target is not None
    assert target.edit_path == live.resolve()
    assert target.document is not None
    assert target.document.sections[0].plain_text == "ok\n"


def test_followed_file_document_inherits_landed_parent_context(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    live = _write(second / "src" / "foo.py")

    target = resolve_ref("src/foo.py", context=_context(first, second))

    assert target is not None
    assert target.document is not None
    assert target.document.link_context is not None
    assert target.document.link_context.base_dirs == (
        live.parent.resolve(),
        first.resolve(),
        second.resolve(),
    )


def test_resolve_ref_reroots_a_stale_numbered_clone_path(tmp_path: Path) -> None:
    stale = tmp_path / "sase_9" / "src" / "foo.py"
    live = _write(tmp_path / "primary" / "src" / "foo.py")

    target = resolve_ref(str(stale), context=_context(tmp_path / "primary"))

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_ref_parses_a_line_suffix_into_scroll_and_edit_line(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "notes.py", "a\nb\nc\n")

    target = resolve_ref(f"{path}:2")

    assert target is not None
    assert target.scroll_line == 2
    assert target.edit_line == 2
    assert target.edit_path == path


def test_resolve_ref_parses_a_line_column_suffix(tmp_path: Path) -> None:
    path = _write(tmp_path / "notes.py")

    target = resolve_ref(f"{path}:8:3")

    assert target is not None
    assert target.scroll_line == 8
    assert target.edit_line == 8
    assert target.edit_column == 3


def test_resolve_ref_strips_a_trailing_dot_candidate(tmp_path: Path) -> None:
    path = _write(tmp_path / "notes.py")

    target = resolve_ref(f"{path}.")

    assert target is not None
    assert target.edit_path == path


def test_resolve_ref_strips_a_git_diff_prefix(tmp_path: Path) -> None:
    live = _write(tmp_path / "src" / "foo.py")

    target = resolve_ref("a/src/foo.py", context=_context(tmp_path))

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_ref_none_context_still_resolves_cwd_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    live = _write(tmp_path / "src" / "foo.py")

    target = resolve_ref("src/foo.py")

    assert target is not None
    assert target.edit_path == live.resolve()


def test_resolve_link_returns_dead_end_diagnostics_from_one_search(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    context = _context(first, second)

    resolution = resolve_link("src/x.py", context=context)

    assert resolution.target is None
    assert resolution.unresolved_message == "src/x.py not found (searched 2 locations)"
    assert resolve_ref("src/x.py", context=context) is None


def test_resolve_ref_parses_markdown_line_fragment(tmp_path: Path) -> None:
    path = _write(tmp_path / "docs" / "guide.md", "one\ntwo\nthree\nfour\n")

    target = resolve_ref("docs/guide.md#L3-L4", context=_context(tmp_path))

    assert target is not None
    assert target.edit_path == path.resolve()
    assert target.scroll_line == 3
    assert target.edit_line == 3


def test_resolve_ref_parses_markdown_heading_fragment(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "docs" / "guide.md",
        "# Intro\nbody\n## Target Heading\nsection\n",
    )

    target = resolve_ref("docs/guide.md#target-heading", context=_context(tmp_path))

    assert target is not None
    assert target.edit_path == path.resolve()
    assert target.scroll_line == 3
    assert target.edit_line == 3


def test_resolve_link_reports_missing_markdown_fragment(tmp_path: Path) -> None:
    path = _write(tmp_path / "docs" / "guide.md", "# Intro\nbody\n")

    resolution = resolve_link("docs/guide.md#missing", context=_context(tmp_path))

    assert resolution.target is None
    assert resolution.unresolved_message == (
        f"fragment #missing was not found in {path.resolve()}"
    )
