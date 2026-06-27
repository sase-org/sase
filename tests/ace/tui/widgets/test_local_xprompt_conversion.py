"""Unit tests for the pure local-xprompt conversion helpers (``gX``).

These cover the conversion *decisions* without a Textual app: name normalization
and validation, Jinja input inference, and invocation skeleton generation.
"""

from __future__ import annotations

from sase.ace.tui.widgets._local_xprompt_conversion import (
    build_local_xprompt,
    infer_local_xprompt_inputs,
    local_xprompt_invocation_skeleton,
    normalize_local_xprompt_name,
    validate_local_xprompt_name,
)
from sase.xprompt.models import InputType
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE


# -- name normalization -----------------------------------------------------


def test_normalize_adds_underscore_prefix() -> None:
    assert normalize_local_xprompt_name("rules") == "_rules"


def test_normalize_keeps_existing_underscore_without_doubling() -> None:
    assert normalize_local_xprompt_name("_rules") == "_rules"


def test_normalize_strips_surrounding_whitespace() -> None:
    assert normalize_local_xprompt_name("  rules  ") == "_rules"


def test_normalize_blank_is_empty() -> None:
    assert normalize_local_xprompt_name("   ") == ""


# -- name validation --------------------------------------------------------


def test_validate_accepts_underscore_name() -> None:
    assert validate_local_xprompt_name("_rules", set()) == ""


def test_validate_rejects_empty() -> None:
    assert validate_local_xprompt_name("", set()) == "name is required"


def test_validate_rejects_non_identifier() -> None:
    assert validate_local_xprompt_name("_my rules", set()) != ""


def test_validate_rejects_duplicate() -> None:
    error = validate_local_xprompt_name("_rules", {"_rules"})
    assert "already exists" in error


# -- Jinja input inference --------------------------------------------------


def test_infer_no_jinja_yields_no_inputs() -> None:
    assert infer_local_xprompt_inputs("Plain prompt body") == []


def test_infer_unknown_variables_become_text_inputs() -> None:
    inputs = infer_local_xprompt_inputs("Review {{ topic }} with {{ details }}")
    assert inputs is not None
    assert [arg.name for arg in inputs] == ["details", "topic"]
    assert all(arg.type is InputType.TEXT for arg in inputs)
    # No default -> required inputs.
    from sase.xprompt.models import UNSET

    assert all(arg.default is UNSET for arg in inputs)


def test_infer_known_globals_are_not_inputs() -> None:
    # ``root`` is a known top-level global, so it is never inferred as an input.
    assert infer_local_xprompt_inputs("Path is {{ root }}") == []


def test_infer_known_globals_without_runtime_value(monkeypatch) -> None:
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    assert infer_local_xprompt_inputs("Path is {{ root }}") == []


def test_infer_invalid_jinja_returns_none() -> None:
    assert infer_local_xprompt_inputs("Broken {{ unclosed ") is None


# -- skeleton generation ----------------------------------------------------


def test_skeleton_without_inputs_is_bare_reference() -> None:
    xprompt = build_local_xprompt("_rules", "do the thing", [])
    assert xprompt.source_path == LOCAL_XPROMPT_SOURCE
    assert local_xprompt_invocation_skeleton(xprompt) == "#_rules"


def test_skeleton_with_inputs_uses_named_args_and_tabstops() -> None:
    inputs = infer_local_xprompt_inputs("Review {{ topic }} with {{ details }}")
    assert inputs is not None
    xprompt = build_local_xprompt("_rules", "body", inputs)
    assert (
        local_xprompt_invocation_skeleton(xprompt) == "#_rules(details=$1, topic=$2)$0"
    )
