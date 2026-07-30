"""Tests for canonical structured output-variable rendering."""

from __future__ import annotations

from sase.core.output_variable_display import (
    VarLine,
    format_var_value_block,
    format_var_value_inline,
    format_var_value_lines,
    var_value_is_container,
    var_value_preview,
)


def test_worked_example_block_form_is_sorted_and_yaml_shaped() -> None:
    value = {
        "report_path": "dist/report.md",
        "status": "ok",
        "metrics": {
            "duration_s": 42.5,
            "passed": True,
            "suites": ["unit", "integration"],
        },
        "findings": [
            {"file": "src/a.py", "severity": "high"},
            {"file": "src/b.py", "severity": "low"},
        ],
        "notes": "first line\nsecond line",
        "empty_list": [],
        "version": "3",
    }

    rendered, truncated = format_var_value_block(value)

    assert not truncated
    assert rendered == "\n".join(
        (
            "empty_list: []",
            "findings:",
            "  - file: src/a.py",
            "    severity: high",
            "  - file: src/b.py",
            "    severity: low",
            "metrics:",
            "  duration_s: 42.5",
            "  passed: true",
            "  suites:",
            "    - unit",
            "    - integration",
            "notes: |",
            "  first line",
            "  second line",
            "report_path: dist/report.md",
            "status: ok",
            'version: "3"',
        )
    )


def test_string_quoting_rules_and_empty_containers() -> None:
    value = {
        "bare": "hello world",
        "bool": "false",
        "empty": "",
        "indicator": "- item",
        "map": {},
        "number": "3.0",
        "space": " padded ",
    }

    rendered, _ = format_var_value_block(value)

    assert rendered == "\n".join(
        (
            "bare: hello world",
            'bool: "false"',
            'empty: ""',
            'indicator: "- item"',
            "map: {}",
            'number: "3.0"',
            'space: " padded "',
        )
    )


def test_list_of_maps_keeps_nested_container_indentation() -> None:
    value = [{"cfg": {"hosts": ["one", "two"]}, "status": "ok"}]

    rendered, _ = format_var_value_block(value)

    assert rendered == "\n".join(
        (
            "- cfg:",
            "    hosts:",
            "      - one",
            "      - two",
            "  status: ok",
        )
    )


def test_styleable_lines_report_kind_key_bullet_and_indent() -> None:
    lines, truncated = format_var_value_lines({"items": [1, False, None]})

    assert not truncated
    assert lines == [
        VarLine(0, False, "items", None, "list"),
        VarLine(1, True, None, "1", "number"),
        VarLine(1, True, None, "false", "boolean"),
        VarLine(1, True, None, "null", "null"),
    ]


def test_line_limit_returns_prefix_and_truncation_flag() -> None:
    full, _ = format_var_value_lines({"items": [1, 2, 3]})
    limited, truncated = format_var_value_lines(
        {"items": [1, 2, 3]},
        max_lines=2,
    )

    assert limited == full[:2]
    assert truncated
    assert format_var_value_lines({"items": [1]}, max_lines=0) == ([], True)


def test_inline_rendering_is_sorted_preserves_list_order_and_truncates_exactly() -> (
    None
):
    value = {"suites": ["unit", "integration"], "passed": True}
    full = "{passed: true, suites: [unit, integration]}"

    assert format_var_value_inline(value, max_chars=100) == full
    assert format_var_value_inline(value, max_chars=12) == "{passed: tr…"
    assert len(format_var_value_inline(value, max_chars=12)) == 12
    assert format_var_value_inline(value, max_chars=1) == "…"
    assert format_var_value_inline(value, max_chars=0) == ""


def test_preview_uses_first_meaningful_scalar_line_and_inline_containers() -> None:
    assert var_value_preview("\n  first   line \nsecond", max_chars=100) == (
        "first line"
    )
    assert var_value_preview("123", max_chars=100) == '"123"'
    assert var_value_preview([], max_chars=100) == "[]"
    assert var_value_preview({"b": 2, "a": 1}, max_chars=100) == "{a: 1, b: 2}"
    assert var_value_is_container([])
    assert var_value_is_container({})
    assert not var_value_is_container("value")
