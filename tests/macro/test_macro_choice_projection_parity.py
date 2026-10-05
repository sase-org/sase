"""The Python projections use the same core choice contract as the editor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.rust import require_rust_binding
from sase.macro._parsing import iter_macro_references
from sase.macro.input_binding import bind_input_args
from sase.macro.models import UNSET, InputArg, InputChoice, InputType

_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / ("macro_arg_choice_completion.json")
)
_CORE_CORPUS_RELATIVE = (
    Path("crates")
    / "sase_core"
    / "tests"
    / "fixtures"
    / "macro_arg_choice_completion.json"
)


def _load_corpus() -> dict[str, Any]:
    corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["schema_version"] == 1
    return corpus


def _core_corpus_candidates() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "sase" / "repos" / "linked" / "sase-core" / _CORE_CORPUS_RELATIVE,
        repo_root.parent / "sase-core" / _CORE_CORPUS_RELATIVE,
    ]


def _input_hint(input_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": input_row["name"],
        "type": input_row["type"],
        "description": input_row.get("description"),
        "required": input_row["required"],
        "default_display": input_row.get("default_display"),
        "position": input_row["position"],
        "repeatable": input_row["repeatable"],
        "choices": input_row.get("choices", []),
        "named_type": input_row.get("named_type"),
        "value_role": input_row.get("value_role"),
    }


def _input_args(input_rows: list[dict[str, Any]]) -> list[InputArg]:
    return [
        InputArg(
            name=row["name"],
            type=InputType(row["type"]),
            default=UNSET if row["required"] else None,
            repeatable=row["repeatable"],
            choices=tuple(
                InputChoice(
                    choice["value"],
                    choice.get("label"),
                    choice.get("description"),
                )
                for choice in row.get("choices", [])
            ),
            named_type=row.get("named_type"),
            value_role=row.get("value_role"),
        )
        for row in input_rows
    ]


def _parse_and_bind(source: str, input_rows: list[dict[str, Any]]) -> dict[str, Any]:
    references = iter_macro_references(source)
    assert len(references) == 1
    positional, named = references[0].parse_arguments()
    bound = bind_input_args(_input_args(input_rows), positional, named)
    return bound.explicit_values


def test_choice_completion_corpus_matches_opened_core_checkout() -> None:
    matches = [path for path in _core_corpus_candidates() if path.is_file()]
    if not matches:
        pytest.skip("opened sase-core checkout with completion corpus is unavailable")

    expected = _CORPUS_PATH.read_bytes()
    for path in matches:
        assert path.read_bytes() == expected, path


@pytest.mark.parametrize(
    "case", _load_corpus()["cases"], ids=lambda case: str(case["id"])
)
def test_python_projection_uses_core_candidates_and_binder(
    case: dict[str, Any],
) -> None:
    """Every golden case reaches the Rust builder and edits bind through Python."""
    source_bytes = case["source"].encode("utf-8")
    replace_start, replace_end = case["replacement_byte_span"]
    cursor = case["cursor_byte"]
    active_name = case.get("expected_active_input")
    rows = case["inputs"]
    active = next((row for row in rows if row["name"] == active_name), rows[0])
    hint = _input_hint(active)

    partial = source_bytes[replace_start:cursor].decode("utf-8")
    partial = partial.lstrip("\"'")
    partial = case.get("builder_partial", partial)
    replacement = source_bytes[replace_start:replace_end].decode("utf-8")
    selected = case.get("selected_values", [])
    candidates = require_rust_binding("macro_argument_choice_candidates")(
        {
            "hint": hint,
            "partial": partial,
            "replacement": replacement,
            "selected": selected,
        }
    )

    if "expected_candidates" in case:
        assert [row["value"] for row in candidates] == case["expected_candidates"]
    if "expected_candidates_contains" in case:
        assert case["expected_candidates_contains"] in {
            row["value"] for row in candidates
        }
    if "expected_insertions" in case:
        assert [row["insertion"] for row in candidates] == case["expected_insertions"]
    if "expected_default" in case:
        assert any(
            row["value"] == case["expected_default"] and row["is_default"]
            for row in candidates
        )

    if case.get("binds_to"):
        bound = _parse_and_bind(case["source"], rows)
        assert bound[case["binds_to"]] == case["source"].split(":", 1)[1]

    for value, expected_text in case.get("applied_edits", {}).items():
        candidate = next(row for row in candidates if row["value"] == value)
        edited = (
            source_bytes[:replace_start]
            + candidate["insertion"].encode("utf-8")
            + source_bytes[replace_end:]
        ).decode("utf-8")
        assert edited == expected_text
        bound_value = _parse_and_bind(edited, rows)[active["name"]]
        expected_bound_value = value == "true" if active["type"] == "bool" else value
        assert bound_value == expected_bound_value
