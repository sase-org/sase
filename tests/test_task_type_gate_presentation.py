"""Frozen task-type gate presentation: resolve, parse, and project."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sase.task_type_gate_presentation import (
    TaskTypeGateDisplay,
    parse_task_type_gate_display,
    resolve_task_type_gate_display,
    task_type_gate_chip,
    task_type_gate_display_payload,
    task_type_gate_markdown_fact,
    task_type_gate_note,
)
from sase.task_type_presentation import (
    UNKNOWN_TASK_TYPE_GLYPH,
    format_task_type_chip,
    task_type_chip,
    task_type_presentation,
)

_FLAKE_FIELDS = {
    "node_id": "tests/x.py::test_y",
    "evidence": "3/50 under -n 8",
}

_BUILTIN_DISPLAY = (
    ("bug", "⨯", "Bug", "#FF5F5F"),
    ("ci", "⚙", "CI failure", "#D7D700"),
    ("feature", "✦", "Feature", "#5FD75F"),
    ("flake", "≈", "Flaky test", "#00D7D7"),
    ("memory", "▤", "Memory", "#8787FF"),
)

_REGISTRY_CALLS = frozenset(
    {
        "get_task_type_registry",
        "task_type_presentation",
        "task_type_snapshot_entry",
    }
)
_RESOLVER_FUNCTIONS = frozenset(
    {
        "resolve_task_type_gate_display",
        "_resolve_facts",
        "_spec_fields",
    }
)


@pytest.mark.parametrize(("slug", "glyph", "name", "accent"), _BUILTIN_DISPLAY)
def test_resolve_each_builtin_type(
    slug: str, glyph: str, name: str, accent: str
) -> None:
    display = resolve_task_type_gate_display(slug, {})

    assert display is not None
    assert display.glyph == glyph
    assert display.name == name
    assert display.accent_color == accent
    assert display.facts == ()
    live = task_type_presentation(slug)
    assert display.glyph == live.glyph
    assert display.accent_color == live.accent_color
    assert display.name == live.label


def test_untyped_bead_resolves_to_none() -> None:
    assert resolve_task_type_gate_display("", {"node_id": "x"}) is None
    assert resolve_task_type_gate_display("   ", {}) is None


def test_unresolved_slug_degrades_to_question_mark_and_raw_field_names() -> None:
    display = resolve_task_type_gate_display(
        "not-a-real-type",
        {"foo": "bar", "baz": "qux"},
    )

    assert display is not None
    assert display.glyph == UNKNOWN_TASK_TYPE_GLYPH
    assert display.name == "not-a-real-type"
    assert display.accent_color == "#6C6C6C"
    assert display.facts == (("foo", "bar"), ("baz", "qux"))


def test_facts_follow_required_spec_order_not_stored_order() -> None:
    display = resolve_task_type_gate_display(
        "flake",
        {
            "evidence": "3/50 under -n 8",
            "repro_cmd": "pytest -n 8",
            "node_id": "tests/x.py::test_y",
        },
    )

    assert display is not None
    assert display.facts == (
        ("Test node ID", "tests/x.py::test_y"),
        ("Evidence", "3/50 under -n 8"),
    )


def test_missing_or_empty_required_value_drops_that_pair() -> None:
    display = resolve_task_type_gate_display(
        "flake",
        {"node_id": "tests/x.py::test_y", "evidence": "  \n  "},
    )

    assert display is not None
    assert display.facts == (("Test node ID", "tests/x.py::test_y"),)


def test_newlines_in_values_collapse_to_spaces() -> None:
    display = resolve_task_type_gate_display(
        "flake",
        {"node_id": "tests/x.py::test_y", "evidence": "3/50\nunder\n-n 8"},
    )

    assert display is not None
    assert display.facts == (
        ("Test node ID", "tests/x.py::test_y"),
        ("Evidence", "3/50 under -n 8"),
    )


def test_fact_values_truncate_to_eighty_cells() -> None:
    display = resolve_task_type_gate_display(
        "flake",
        {"node_id": "x" * 81, "evidence": "ok"},
    )

    assert display is not None
    assert display.facts[0] == ("Test node ID", "x" * 79 + "…")
    assert display.facts[1] == ("Evidence", "ok")


def test_three_pair_cap_keeps_spec_order() -> None:
    display = resolve_task_type_gate_display(
        "unknown-four-field-type",
        {"a": "1", "b": "2", "c": "3", "d": "4"},
    )

    assert display is not None
    assert display.facts == (("a", "1"), ("b", "2"), ("c", "3"))


def test_projections_match_the_plan_examples() -> None:
    display = resolve_task_type_gate_display("flake", _FLAKE_FIELDS)
    assert display is not None

    assert task_type_gate_display_payload(display) == {
        "glyph": "≈",
        "name": "Flaky test",
        "accent_color": "#00D7D7",
        "facts": [
            ["Test node ID", "tests/x.py::test_y"],
            ["Evidence", "3/50 under -n 8"],
        ],
    }
    assert task_type_gate_chip(display, "flake") == {
        "glyph": "≈",
        "label": "flake",
        "color": "#00D7D7",
    }
    assert (
        task_type_gate_note(display)
        == "Flaky test · Test node ID: tests/x.py::test_y · Evidence: 3/50 under -n 8"
    )
    assert task_type_gate_markdown_fact(display, "flake") == "**Task type:** ≈ `flake`"


def test_frozen_chip_and_live_chip_share_the_same_formatter() -> None:
    display = resolve_task_type_gate_display("flake", {})
    assert display is not None
    chip = task_type_gate_chip(display, "flake")
    laid_out = format_task_type_chip(chip["glyph"], chip["label"])

    assert laid_out == "≈ flake"
    assert task_type_chip("flake").plain == f" {laid_out} "


def test_note_without_facts_is_just_the_human_name() -> None:
    display = resolve_task_type_gate_display("flake", {})
    assert display is not None
    assert task_type_gate_note(display) == "Flaky test"


def test_markdown_fact_escapes_backticks_in_the_slug() -> None:
    display = resolve_task_type_gate_display("flake", {})
    assert display is not None
    assert (
        task_type_gate_markdown_fact(display, "fla`ke") == "**Task type:** ≈ `fla\\`ke`"
    )


def test_resolve_payload_parse_is_the_identity() -> None:
    for slug, _glyph, _name, _accent in _BUILTIN_DISPLAY:
        fields = _FLAKE_FIELDS if slug == "flake" else {}
        display = resolve_task_type_gate_display(slug, fields)
        assert display is not None
        parsed = parse_task_type_gate_display(task_type_gate_display_payload(display))
        assert parsed == display

    unknown = resolve_task_type_gate_display("ghost-type", {"k": "v"})
    assert unknown is not None
    assert (
        parse_task_type_gate_display(task_type_gate_display_payload(unknown)) == unknown
    )


def test_parser_accepts_the_resolver_payload_and_tuple_facts() -> None:
    payload = {
        "glyph": "≈",
        "name": "Flaky test",
        "accent_color": "#00D7D7",
        "facts": (("Test node ID", "tests/x.py::test_y"),),
    }

    parsed = parse_task_type_gate_display(payload)

    assert parsed == TaskTypeGateDisplay(
        glyph="≈",
        name="Flaky test",
        accent_color="#00D7D7",
        facts=(("Test node ID", "tests/x.py::test_y"),),
    )


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        "flake",
        7,
        [],
        {},
        {"glyph": "≈", "name": "Flaky test", "accent_color": "#00D7D7"},
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [],
            "extra": 1,
        },
        {"glyph": "", "name": "Flaky test", "accent_color": "#00D7D7", "facts": []},
        {"glyph": "ab", "name": "Flaky test", "accent_color": "#00D7D7", "facts": []},
        {"glyph": " ≈ ", "name": "Flaky test", "accent_color": "#00D7D7", "facts": []},
        {"glyph": "≈", "name": "", "accent_color": "#00D7D7", "facts": []},
        {"glyph": "≈", "name": " Flaky test", "accent_color": "#00D7D7", "facts": []},
        {"glyph": "≈", "name": "Flaky\ntest", "accent_color": "#00D7D7", "facts": []},
        {"glyph": "≈", "name": "Flaky test", "accent_color": "00D7D7", "facts": []},
        {"glyph": "≈", "name": "Flaky test", "accent_color": "#00D7D7 ", "facts": []},
        {"glyph": "≈", "name": "Flaky test", "accent_color": "#00D7D7", "facts": {}},
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"]],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [["a"]],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [["a", "1", "x"]],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": ["ab"],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [[1, "v"]],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [["", "v"]],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [["L", "v\nw"]],
        },
        {
            "glyph": "≈",
            "name": "Flaky test",
            "accent_color": "#00D7D7",
            "facts": [["L", "x" * 81]],
        },
    ],
)
def test_parser_rejects_malformed_mappings(mapping: object) -> None:
    with pytest.raises(ValueError):
        parse_task_type_gate_display(mapping)


def test_only_the_resolver_reads_the_registry() -> None:
    module_path = Path(__file__).resolve().parents[1] / (
        "src/sase/task_type_gate_presentation.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in _RESOLVER_FUNCTIONS:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in _REGISTRY_CALLS:
                offenders.append(node.name)
                break
            if isinstance(child, ast.Attribute) and child.attr in _REGISTRY_CALLS:
                offenders.append(node.name)
                break
    assert offenders == []


def test_module_does_not_import_notification_gates() -> None:
    module_path = Path(__file__).resolve().parents[1] / (
        "src/sase/task_type_gate_presentation.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    assert all("notification_gates" not in name for name in imported)
