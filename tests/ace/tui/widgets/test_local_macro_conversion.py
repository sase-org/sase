"""Unit tests for the pure local-macro conversion helpers (``gL``).

These cover the conversion *decisions* without a Textual app: name normalization
and validation, Jinja input inference, and invocation skeleton generation.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets._local_macro_conversion as conversion_module
from sase.ace.tui.widgets._local_macro_conversion import (
    build_local_macro,
    convert_placeholders_to_inputs,
    infer_local_macro_inputs,
    local_macro_invocation_skeleton,
    normalize_local_macro_name,
    validate_local_macro_name,
)
from sase.macro.models import InputType
from sase.macro.prompt_frontmatter import LOCAL_MACRO_SOURCE


def _disable_placeholder_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn off ``ace.prompt_inputs.macro_placeholder_args``."""
    monkeypatch.setattr(
        conversion_module,
        "load_merged_config",
        lambda: {"ace": {"prompt_inputs": {"macro_placeholder_args": False}}},
    )


# -- name normalization -----------------------------------------------------


def test_normalize_adds_underscore_prefix() -> None:
    assert normalize_local_macro_name("rules") == "_rules"


def test_normalize_keeps_existing_underscore_without_doubling() -> None:
    assert normalize_local_macro_name("_rules") == "_rules"


def test_normalize_strips_surrounding_whitespace() -> None:
    assert normalize_local_macro_name("  rules  ") == "_rules"


def test_normalize_blank_is_empty() -> None:
    assert normalize_local_macro_name("   ") == ""


# -- name validation --------------------------------------------------------


def test_validate_accepts_underscore_name() -> None:
    assert validate_local_macro_name("_rules", set()) == ""


def test_validate_rejects_empty() -> None:
    assert validate_local_macro_name("", set()) == "name is required"


def test_validate_rejects_non_identifier() -> None:
    assert validate_local_macro_name("_my rules", set()) != ""


def test_validate_rejects_duplicate() -> None:
    error = validate_local_macro_name("_rules", {"_rules"})
    assert "already exists" in error


# -- Jinja input inference --------------------------------------------------


def test_infer_no_jinja_yields_no_inputs() -> None:
    conversion = infer_local_macro_inputs("Plain prompt body")
    assert conversion is not None
    assert conversion.body == "Plain prompt body"
    assert conversion.inputs == []
    assert conversion.renames == {}


def test_infer_unknown_variables_become_text_inputs() -> None:
    conversion = infer_local_macro_inputs("Review {{ topic }} with {{ details }}")
    assert conversion is not None
    assert [arg.name for arg in conversion.inputs] == ["details", "topic"]
    assert all(arg.type is InputType.TEXT for arg in conversion.inputs)
    # No default -> required inputs.
    from sase.macro.models import UNSET

    assert all(arg.default is UNSET for arg in conversion.inputs)


def test_infer_known_globals_are_not_inputs() -> None:
    # ``root`` is a known top-level global, so it is never inferred as an input.
    conversion = infer_local_macro_inputs("Path is {{ root }}")
    assert conversion is not None
    assert conversion.inputs == []


def test_infer_known_globals_without_runtime_value(monkeypatch) -> None:
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    conversion = infer_local_macro_inputs("Path is {{ root }}")
    assert conversion is not None
    assert conversion.inputs == []


def test_infer_invalid_jinja_returns_none() -> None:
    assert infer_local_macro_inputs("Broken {{ unclosed ") is None


def test_infer_runtime_builtins_are_not_inputs() -> None:
    # Run builtins, conditionals, and positionals render from the agent run,
    # so they are never inferred as helper inputs.
    conversion = infer_local_macro_inputs(
        "{{ wait.chats }} {{ patch_name }} {{ n }} {{ _1 }} for {{ topic }}"
    )
    assert conversion is not None
    assert [arg.name for arg in conversion.inputs] == ["topic"]


# -- skeleton generation ----------------------------------------------------


def test_skeleton_without_inputs_is_bare_reference() -> None:
    macro = build_local_macro("_rules", "do the thing", [])
    assert macro.source_path == LOCAL_MACRO_SOURCE
    assert local_macro_invocation_skeleton(macro) == "#_rules"


def test_skeleton_with_inputs_uses_named_args_and_tabstops() -> None:
    conversion = infer_local_macro_inputs("Review {{ topic }} with {{ details }}")
    assert conversion is not None
    macro = build_local_macro("_rules", "body", conversion.inputs)
    assert local_macro_invocation_skeleton(macro) == "#_rules(details=$1, topic=$2)$0"


# -- raw placeholder conversion --------------------------------------------


def test_placeholder_conversion_reuses_existing_name() -> None:
    converted = convert_placeholders_to_inputs(
        "Deploy <service> using {{ service }}",
        existing={"service"},
    )
    assert converted.body == "Deploy {{ service }} using {{ service }}"
    assert converted.inputs == []
    assert converted.renames == {"service": "service"}


def test_placeholder_conversion_resolves_slug_collisions() -> None:
    converted = convert_placeholders_to_inputs("Compare <the plan> with <the-plan>")
    assert converted.body == ("Compare {{ the_plan }} with {{ the_plan_2 }}")
    assert [arg.name for arg in converted.inputs] == ["the_plan", "the_plan_2"]
    assert all(arg.type is InputType.TEXT for arg in converted.inputs)


def test_placeholder_conversion_preserves_literal_placeholders() -> None:
    converted = convert_placeholders_to_inputs(
        "Replace <live>, not `<inline>` or:\n```\n<fenced>\n```"
    )
    assert converted.body == (
        "Replace {{ live }}, not `<inline>` or:\n```\n<fenced>\n```"
    )
    assert [arg.name for arg in converted.inputs] == ["live"]


def test_placeholder_conversion_disabled_is_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_placeholder_args(monkeypatch)

    converted = convert_placeholders_to_inputs("Deploy <service> now")

    assert converted.body == "Deploy <service> now"
    assert converted.inputs == []
    assert converted.renames == {}


def test_local_inference_disabled_keeps_only_jinja_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_placeholder_args(monkeypatch)

    converted = infer_local_macro_inputs("Deploy {{ target }} with <service>")

    assert converted is not None
    assert converted.body == "Deploy {{ target }} with <service>"
    assert [arg.name for arg in converted.inputs] == ["target"]
    assert converted.renames == {}


def test_local_inference_disabled_invalid_jinja_still_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_placeholder_args(monkeypatch)

    assert infer_local_macro_inputs("Broken {{ unclosed with <service>") is None


def test_placeholder_conversion_config_failure_falls_back_to_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_config_error() -> dict[str, object]:
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(
        conversion_module,
        "load_merged_config",
        _raise_config_error,
    )

    converted = convert_placeholders_to_inputs("Deploy <service> now")

    assert converted.body == "Deploy {{ service }} now"
    assert [arg.name for arg in converted.inputs] == ["service"]
    assert converted.renames == {"service": "service"}


def test_local_inference_appends_placeholder_inputs_after_jinja_inputs() -> None:
    converted = infer_local_macro_inputs(
        "Use {{ zulu }} with <the plan> and {{ alpha }}"
    )
    assert converted is not None
    assert converted.body == ("Use {{ zulu }} with {{ the_plan }} and {{ alpha }}")
    assert [arg.name for arg in converted.inputs] == [
        "alpha",
        "zulu",
        "the_plan",
    ]


def test_local_inference_reuses_matching_jinja_input() -> None:
    converted = infer_local_macro_inputs("Use <service> and {{ service }}")
    assert converted is not None
    assert converted.body == "Use {{ service }} and {{ service }}"
    assert [arg.name for arg in converted.inputs] == ["service"]
