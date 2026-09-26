"""Tests for shared ``=alias``/``==model`` edit payload parsing."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.widgets._model_shortcut_edits import (
    apply_model_shortcut_edit,
    parse_model_shortcut_edit_payload,
)


def _position(character: int) -> dict[str, int]:
    return {"line": 0, "character": character}


def _edit(start: int, end: int, new_text: str) -> dict[str, Any]:
    return {
        "range": {"start": _position(start), "end": _position(end)},
        "new_text": new_text,
    }


def test_parse_accepts_legacy_single_edit_payload_without_additional_edits() -> None:
    """Payloads planned before ``additional_edits`` still expand in place."""
    text = "Use =la now"
    planned = parse_model_shortcut_edit_payload(
        text,
        {
            "schema_version": 1,
            "kind": "alias",
            "value": "@large",
            "replacement": "%m:@large ",
            "edit": _edit(4, 8, "%m:@large "),
            "caret": _position(14),
        },
    )

    assert planned is not None
    assert (planned.replacement_start, planned.replacement_end) == (4, 8)
    assert planned.replacement == "%m:@large "
    assert planned.additional_edits == ()
    assert planned.caret_offset == 14
    assert (
        apply_model_shortcut_edit(
            text,
            planned.replacement_start,
            planned.replacement_end,
            planned.replacement,
            planned.additional_edits,
        )
        == "Use %m:@large now"
    )


def test_parse_accepts_multi_edit_payload_with_adjacent_removal() -> None:
    """The shrunk second removal survives the wire as an extra edit."""
    text = "=la %m:a %m:b"
    planned = parse_model_shortcut_edit_payload(
        text,
        {
            "schema_version": 1,
            "kind": "alias",
            "value": "@large",
            "replacement": "%m:@large ",
            "edit": _edit(0, 4, ""),
            "caret": _position(10),
            "additional_edits": [
                _edit(4, 9, "%m:@large "),
                _edit(9, 13, ""),
            ],
        },
    )

    assert planned is not None
    assert (planned.replacement_start, planned.replacement_end) == (0, 4)
    assert planned.replacement == ""
    assert len(planned.additional_edits) == 2
    assert planned.caret_offset == 10
    assert (
        apply_model_shortcut_edit(
            text,
            planned.replacement_start,
            planned.replacement_end,
            planned.replacement,
            planned.additional_edits,
        )
        == "%m:@large "
    )


def test_parse_rejects_overlapping_spans_fail_closed() -> None:
    """A corrupt multi-edit plan parses to None so nothing is applied."""
    text = "=la %m:a %m:b"
    assert (
        parse_model_shortcut_edit_payload(
            text,
            {
                "schema_version": 1,
                "kind": "alias",
                "value": "@large",
                "replacement": "%m:@large ",
                "edit": _edit(0, 4, ""),
                "caret": _position(10),
                "additional_edits": [
                    _edit(4, 9, "%m:@large "),
                    _edit(8, 13, ""),
                ],
            },
        )
        is None
    )
