"""Tests for hint extraction and parsing functions."""

from sase.ace.hints import (
    _expand_hint_part,
    build_editor_args,
    is_rerun_input,
    parse_edit_hooks_input,
    parse_test_targets,
    parse_view_input,
)

# --- Tests for is_rerun_input ---


def test_is_rerun_input_empty() -> None:
    """Empty input is not a rerun input."""
    assert is_rerun_input("") is False


def test_is_rerun_input_rejects_double_at() -> None:
    """Double @@ suffix is rejected."""
    assert is_rerun_input("1@@") is False


def test_is_rerun_input_rejects_test_targets() -> None:
    """Test targets (starting with //) are rejected."""
    assert is_rerun_input("//foo:bar") is False


# --- Tests for parse_view_input ---


def test_parse_view_input_empty() -> None:
    """Empty input returns empty results."""
    files, open_in_editor, copy_to_clipboard, invalid = parse_view_input(
        "", {0: "/path/to/file"}
    )
    assert files == []
    assert open_in_editor is False
    assert copy_to_clipboard is False
    assert invalid == []


def test_parse_view_input_standalone_at() -> None:
    """Standalone @ is skipped (no longer supported as shorthand)."""
    hint_mappings = {0: "/path/project", 1: "/path/file"}
    files, open_in_editor, copy_to_clipboard, invalid = parse_view_input(
        "@", hint_mappings
    )
    # Standalone @ is skipped, so no files are selected
    assert files == []
    # But open_in_editor is still set because @ suffix was detected
    assert open_in_editor is True
    assert copy_to_clipboard is False


def test_parse_view_input_invalid_hint() -> None:
    """Invalid hints are reported."""
    hint_mappings = {0: "/path/a", 1: "/path/b"}
    files, open_in_editor, copy_to_clipboard, invalid = parse_view_input(
        "1 5", hint_mappings
    )
    assert files == ["/path/b"]
    assert invalid == [5]


# --- Tests for parse_edit_hooks_input ---


def test_parse_edit_hooks_input_invalid() -> None:
    """Invalid hints are reported."""
    hint_mappings = {1: "/path/a"}
    rerun, delete, invalid = parse_edit_hooks_input("1 5@", hint_mappings)
    assert rerun == [1]
    assert delete == []
    assert invalid == [5]


# --- Tests for parse_test_targets ---


def test_parse_test_targets_adds_prefix() -> None:
    """Missing // prefix is added."""
    targets = parse_test_targets("//foo:bar baz:qux")
    assert targets == ["//foo:bar", "//baz:qux"]


# --- Tests for build_editor_args ---


def test_build_editor_args_basic() -> None:
    """Basic editor args."""
    args = build_editor_args("vim", ["/path/to/file"])
    assert args == ["vim", "/path/to/file"]


# --- Tests for _expand_hint_part ---


def test_expand_hint_part_invalid_range() -> None:
    """Range with start > end returns empty list."""
    assert _expand_hint_part("10-5") == []


def test_expand_hint_part_invalid_input() -> None:
    """Non-numeric input returns empty list."""
    assert _expand_hint_part("abc") == []


def test_expand_hint_part_invalid_range_format() -> None:
    """Invalid range format returns empty list."""
    assert _expand_hint_part("1-2-3") == []
    assert _expand_hint_part("a-5") == []
    assert _expand_hint_part("1-b") == []


# --- Tests for range support in is_rerun_input ---


def test_is_rerun_input_range() -> None:
    """Ranges are valid rerun input."""
    assert is_rerun_input("1-5") is True


# --- Tests for range support in parse_view_input ---


def test_parse_view_input_range_no_duplicates() -> None:
    """Overlapping ranges don't create duplicate files."""
    hint_mappings = {1: "/a", 2: "/b", 3: "/c"}
    files, _, _, _ = parse_view_input("1-2 2-3", hint_mappings)
    assert files == ["/a", "/b", "/c"]


# --- Tests for % suffix (copy to clipboard) in parse_view_input ---


def test_parse_view_input_standalone_percent() -> None:
    """Standalone % is skipped (not supported as shorthand)."""
    hint_mappings = {0: "/path/project", 1: "/path/file"}
    files, open_in_editor, copy_to_clipboard, invalid = parse_view_input(
        "%", hint_mappings
    )
    # Standalone % is skipped, so no files are selected
    assert files == []
    # But copy_to_clipboard is still set because % suffix was detected
    assert open_in_editor is False
    assert copy_to_clipboard is True


# --- Tests for range support in parse_edit_hooks_input ---


def test_parse_edit_hooks_input_range_delete() -> None:
    """Range with @ suffix marks for delete."""
    hint_mappings = {1: "/a", 2: "/b", 3: "/c"}
    rerun, delete, _ = parse_edit_hooks_input("1-3@", hint_mappings)
    assert rerun == []
    assert delete == [1, 2, 3]
