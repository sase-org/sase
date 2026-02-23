"""Tests for meta_* field helpers in prompt_panel."""

from typing import Any

from sase.ace.tui.widgets.prompt_panel import (
    aggregate_meta_fields,
    extract_meta_fields,
)

# --- format_meta_key tests ---


# --- extract_meta_fields tests ---


def testextract_meta_fields_basic() -> None:
    """Extracts a single meta field."""
    output = {"status": "ok", "meta_new_cl": "my_cl"}
    result = extract_meta_fields(output)
    assert result == [("New Cl", "my_cl")]


# --- aggregate_meta_fields tests ---


def testaggregate_meta_fields_duplicates() -> None:
    """Duplicate keys across steps get #N suffixes."""
    steps = [
        {"output": {"meta_id": "first"}},
        {"output": {"meta_id": "second"}},
    ]
    result = aggregate_meta_fields(steps)
    assert result == [("Id #1", "first"), ("Id #2", "second")]


def testaggregate_meta_fields_empty_output() -> None:
    """Steps with no output or non-dict output are skipped."""
    steps: list[dict[str, Any]] = [
        {"output": None},
        {},
        {"output": "raw string"},
        {"output": {"meta_ok": "yes"}},
    ]
    result = aggregate_meta_fields(steps)
    assert result == [("Ok", "yes")]
