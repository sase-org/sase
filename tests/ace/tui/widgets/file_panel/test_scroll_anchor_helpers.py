"""Unit tests for the pure scroll-anchor helpers (no Textual involved)."""

from __future__ import annotations

from sase.ace.tui.widgets.file_panel._scroll_anchor import (
    AnchorStore,
    _ScrollAnchor,
    capture_anchor,
    content_digest,
    _normalize_row,
    resolve_anchor,
)


def _numbered(number: str, text: str, *, width: int = 3) -> str:
    """Build a Rich ``Syntax(line_numbers=True)``-shaped gutter row."""
    return f"{number.rjust(width)} {text}"


def _blank_gutter(text: str, *, width: int = 3) -> str:
    """Build a wrapped-continuation row with a blank gutter of *width*."""
    return f"{' ' * width} {text}"


def test_normalize_row_strips_gutter_regardless_of_digit_width() -> None:
    assert _normalize_row(_numbered("1", "def foo():")) == "def foo():"
    assert _normalize_row(_numbered("10", "def foo():")) == "def foo():"
    assert _normalize_row(_numbered("100", "def foo():", width=3)) == "def foo():"


def test_normalize_row_strips_blank_continuation_gutter() -> None:
    assert _normalize_row(_blank_gutter("continued text")) == "continued text"


def test_normalize_row_strips_trailing_whitespace() -> None:
    assert _normalize_row(_numbered("1", "trailing   ")) == "trailing"


def test_normalize_row_preserves_content_indentation() -> None:
    assert _normalize_row(_numbered("1", "    indented")) == "    indented"


def test_normalize_row_no_gutter_plain_path() -> None:
    assert _normalize_row("No changes detected.") == "No changes detected."


def test_capture_anchor_row_is_itself_a_line_start() -> None:
    row_texts = [_numbered("1", "first"), _numbered("2", "second")]
    anchor = capture_anchor(1, row_texts, 0, gutter_present=True, content_digest="d1")
    assert anchor.row == 1
    assert anchor.line_start_row_text == "second"
    assert anchor.sub_offset == 0
    assert anchor.content_digest == "d1"


def test_capture_anchor_walks_up_to_line_start_from_continuation_row() -> None:
    row_texts = [
        _numbered("1", "first"),
        _numbered("2", "wrapped line here"),
        _blank_gutter("continues one"),
        _blank_gutter("continues two"),
    ]
    anchor = capture_anchor(3, row_texts, 0, gutter_present=True, content_digest="d1")
    assert anchor.line_start_row_text == "wrapped line here"
    assert anchor.sub_offset == 2


def test_capture_anchor_no_gutter_uses_row_directly() -> None:
    row_texts = ["No changes detected."]
    anchor = capture_anchor(0, row_texts, 0, gutter_present=False, content_digest=None)
    assert anchor.line_start_row_text == "No changes detected."
    assert anchor.sub_offset == 0


def test_capture_anchor_window_exhausted_falls_back_to_window_start() -> None:
    # Only continuation rows are visible in the window; the true line start
    # is out of range. capture_anchor must stop at window_start rather than
    # walking past it.
    row_texts = [_blank_gutter("mid"), _blank_gutter("tail")]
    anchor = capture_anchor(11, row_texts, 10, gutter_present=True, content_digest=None)
    assert anchor.sub_offset == 1
    assert anchor.line_start_row_text == "mid"


def test_resolve_anchor_exact_fast_path_ignores_row_texts() -> None:
    anchor = _ScrollAnchor(
        row=300,
        line_start_row_text="unrelated text",
        sub_offset=0,
        content_digest="same",
    )
    # row_texts intentionally contain no matching text anywhere; the fast
    # path must short-circuit before ever searching.
    row_texts = [_numbered("1", "nothing matches here")]
    resolved = resolve_anchor(
        anchor,
        row_texts,
        0,
        gutter_present=True,
        content_digest="same",
        search_window=5,
    )
    assert resolved == 300


def test_resolve_anchor_relocates_after_content_shifts_down() -> None:
    anchor = _ScrollAnchor(
        row=2, line_start_row_text="target line", sub_offset=0, content_digest="old"
    )
    row_texts = [
        _numbered("1", "prepended a"),
        _numbered("2", "prepended b"),
        _numbered("3", "prepended c"),
        _numbered("4", "prepended d"),
        _numbered("5", "target line"),
    ]
    resolved = resolve_anchor(
        anchor,
        row_texts,
        0,
        gutter_present=True,
        content_digest="new",
        search_window=64,
    )
    assert resolved == 4


def test_resolve_anchor_sub_offset_round_trips_on_wrapped_rows() -> None:
    old_row_texts = [
        _numbered("1", "wrapped source line"),
        _blank_gutter("continuation"),
    ]
    anchor = capture_anchor(
        1, old_row_texts, 0, gutter_present=True, content_digest="old"
    )
    assert anchor.sub_offset == 1

    new_row_texts = [
        _numbered("1", "inserted"),
        _numbered("2", "wrapped source line"),
        _blank_gutter("continuation"),
    ]
    resolved = resolve_anchor(
        anchor,
        new_row_texts,
        0,
        gutter_present=True,
        content_digest="new",
        search_window=64,
    )
    assert resolved == 2


def test_resolve_anchor_only_matches_line_starts_not_coincidental_continuations() -> (
    None
):
    anchor = _ScrollAnchor(
        row=2, line_start_row_text="foo", sub_offset=0, content_digest="old"
    )
    row_texts = [
        _numbered("1", "header"),
        _blank_gutter("foo"),  # coincidental continuation text; must be skipped
        _numbered("2", "foo"),  # the real line start
    ]
    resolved = resolve_anchor(
        anchor,
        row_texts,
        0,
        gutter_present=True,
        content_digest="new",
        search_window=64,
    )
    assert resolved == 2


def test_resolve_anchor_bounded_window_fallback_returns_anchor_row() -> None:
    anchor = _ScrollAnchor(
        row=300, line_start_row_text="never appears", sub_offset=0, content_digest="old"
    )
    row_texts = [_numbered("1", "something else")] * 5
    resolved = resolve_anchor(
        anchor,
        row_texts,
        300,
        gutter_present=True,
        content_digest="new",
        search_window=2,
    )
    assert resolved == 300


def test_content_digest_stable_and_none_for_none_content() -> None:
    assert content_digest(None) is None
    assert content_digest("same") == content_digest("same")
    assert content_digest("a") != content_digest("b")


def test_anchor_store_get_set_round_trip() -> None:
    store = AnchorStore(max_entries=2)
    anchor = _ScrollAnchor(
        row=5, line_start_row_text="x", sub_offset=0, content_digest=None
    )
    assert store.get("key") is None
    store.set("key", anchor)
    assert store.get("key") == anchor


def test_anchor_store_evicts_least_recently_used() -> None:
    store = AnchorStore(max_entries=2)
    a = _ScrollAnchor(
        row=1, line_start_row_text=None, sub_offset=0, content_digest=None
    )
    b = _ScrollAnchor(
        row=2, line_start_row_text=None, sub_offset=0, content_digest=None
    )
    c = _ScrollAnchor(
        row=3, line_start_row_text=None, sub_offset=0, content_digest=None
    )
    store.set("a", a)
    store.set("b", b)
    store.get("a")  # touch "a" so "b" becomes the least recently used
    store.set("c", c)
    assert store.get("b") is None
    assert store.get("a") == a
    assert store.get("c") == c
