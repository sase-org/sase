"""Drive the shared choice golden corpus through the real TUI detector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.widgets._macro_arg_choice_adapter import (
    choice_candidates_for_hint,
)
from sase.ace.tui.widgets.macro_arg_assist import (
    MacroAssistEntry,
    MacroInputHint,
    detect_macro_arg_completion_at_cursor,
)
from sase.macro.models import InputChoice

_CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "macro_arg_choice_completion.json"
)

_KIND_MAP = {
    "macro_argument_value": "macro_arg_value",
    "macro_argument_type_hint": "macro_arg_type_hint",
    "macro_argument_agent": "macro_arg_agent",
    "macro_argument_path": "macro_arg_path",
    "macro_argument_name": "macro_arg_name",
}


def _load_corpus() -> dict:
    corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["schema_version"] == 1
    return corpus


def _byte_to_py(text: str, byte_offset: int) -> int:
    return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))


def _py_to_byte(text: str, py_offset: int) -> int:
    return len(text[:py_offset].encode("utf-8"))


def _entry_for_case(case: dict) -> MacroAssistEntry:
    inputs: list[MacroInputHint] = []
    for row in case["inputs"]:
        inputs.append(
            MacroInputHint(
                name=row["name"],
                type=row["type"],
                required=bool(row["required"]),
                default_display=row.get("default_display"),
                position=int(row["position"]),
                repeatable=bool(row["repeatable"]),
                description=row.get("description"),
                choices=tuple(
                    InputChoice(
                        value=choice["value"],
                        label=choice.get("label"),
                        description=choice.get("description"),
                    )
                    for choice in row.get("choices", [])
                ),
                named_type=row.get("named_type"),
                value_role=row.get("value_role"),
            )
        )
    return MacroAssistEntry(
        name=str(case.get("macro", "macro")),
        insertion=f"#{case.get('macro', 'macro')}",
        reference_prefix="#",
        kind="macro",
        input_signature=None,
        inputs=tuple(inputs),
        content_preview=None,
    )


@pytest.mark.parametrize(
    "case", _load_corpus()["cases"], ids=lambda case: str(case["id"])
)
def test_tui_detection_and_candidates_match_golden_corpus(case: dict) -> None:
    """Every golden case resolves through TUI detection and the Rust builder."""
    source: str = case["source"]
    cursor_byte: int = case["cursor_byte"]
    cursor_py = _byte_to_py(source, cursor_byte)
    entry = _entry_for_case(case)
    ctx = detect_macro_arg_completion_at_cursor(source, cursor_py, [entry])
    assert ctx is not None
    assert ctx.active_input is not None
    expected_kind = _KIND_MAP.get(
        str(case.get("expected_kind", "")), str(case.get("expected_kind", ""))
    )
    assert ctx.completion_kind == expected_kind
    assert ctx.active_input.name == case.get("expected_active_input")
    # Replacement span after UTF-8 coordinate conversion.
    expected_start, expected_end = case["replacement_byte_span"]
    assert _py_to_byte(source, ctx.value_start) == expected_start
    assert _py_to_byte(source, ctx.value_end) == expected_end
    if expected_kind != "macro_arg_value":
        return
    partial = source.encode("utf-8")[expected_start:cursor_byte].decode("utf-8")
    partial = partial.lstrip("\"'")
    partial = case.get("builder_partial", partial)
    replacement = source.encode("utf-8")[expected_start:expected_end].decode("utf-8")
    rows = choice_candidates_for_hint(
        ctx.active_input,
        partial=partial,
        replacement=replacement,
        selected=ctx.selected_values,
    )
    if "expected_candidates" in case:
        assert [row.value for row in rows] == case["expected_candidates"]
    if "expected_candidates_contains" in case:
        assert case["expected_candidates_contains"] in {row.value for row in rows}
    if "expected_insertions" in case:
        assert [row.insertion for row in rows] == case["expected_insertions"]
    if "expected_default" in case:
        assert any(
            row.value == case["expected_default"] and row.is_default for row in rows
        )
    for value, expected_text in case.get("applied_edits", {}).items():
        candidate = next(row for row in rows if row.value == value)
        edited = (
            source.encode("utf-8")[:expected_start]
            + candidate.insertion.encode("utf-8")
            + source.encode("utf-8")[expected_end:]
        ).decode("utf-8")
        assert edited == expected_text
