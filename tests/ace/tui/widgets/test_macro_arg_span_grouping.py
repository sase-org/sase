"""Call-grouped Rust span bounds for repeatable enum inputs."""

from __future__ import annotations

from sase.ace.tui.widgets._macro_arg_assist_detection import (
    _rust_span_bounds_for_cursor,
)


def _span(start: int, end: int, role: str, call_name: str = "m") -> dict:
    return {
        "start": start,
        "end": end,
        "role": role,
        "validity": "ok",
        "source": "macro",
        "call_name": call_name,
    }


def test_adjacent_call_values_do_not_leak() -> None:
    text = "#m(tags=a, tags=) #m(tags=b)"
    # First call: "(" at 2, "a" at 8-9, ")" at 16-17.
    # Second call: "(" at 20, "b" at 26-27.
    spans = [
        _span(2, 3, "arg_delimiter"),
        _span(3, 7, "arg_key"),
        _span(7, 8, "arg_assign"),
        _span(8, 9, "arg_value"),
        _span(9, 10, "arg_delimiter"),
        _span(11, 15, "arg_key"),
        _span(15, 16, "arg_assign"),
        _span(16, 17, "arg_delimiter"),
        _span(20, 21, "arg_delimiter"),
        _span(21, 25, "arg_key"),
        _span(25, 26, "arg_assign"),
        _span(26, 27, "arg_value"),
        _span(27, 28, "arg_delimiter"),
    ]
    cursor = text.index("tags=)", 10) + len("tags=")
    bounds = _rust_span_bounds_for_cursor(text, 0, 17, cursor, "m", spans=spans)
    assert bounds is not None
    _start, _end, selected = bounds
    assert selected == frozenset({"a"})
    assert "b" not in selected


def test_long_call_keeps_all_selected() -> None:
    first = "a" * 70
    second = "b" * 70
    text = f"#m(tags={first}, tags={second}, tags=)"
    first_start = text.index(first)
    first_end = first_start + len(first)
    second_start = text.index(second)
    second_end = second_start + len(second)
    open_at = text.index("(")
    close_at = text.rindex(")")
    cursor = len(text) - 1  # empty value before ")"
    spans = [
        _span(open_at, open_at + 1, "arg_delimiter"),
        _span(first_start, first_end, "arg_value"),
        _span(second_start, second_end, "arg_value"),
        _span(close_at, close_at + 1, "arg_delimiter"),
    ]
    bounds = _rust_span_bounds_for_cursor(text, 0, len(text), cursor, "m", spans=spans)
    assert bounds is not None
    _start, _end, selected = bounds
    assert selected == frozenset({first, second})
