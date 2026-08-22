"""Smoke tests for the Phase 1 frontmatter schema & validation adapter.

:mod:`sase.xprompt.frontmatter_schema` is a thin typed wrapper over the
``sase_core_rs`` bindings. The validation rules, guidance text, and field set
all live in ``sase-core`` (the same engine that backs the xprompt LSP); these
tests pin the adapter's rehydration contract — the schema is non-empty and
ordered, a known-good value validates clean, and a known-bad value yields the
expected diagnostic — without reimplementing any rule on the Python side.
"""

from __future__ import annotations

from sase.xprompt.frontmatter_schema import (
    FrontmatterFieldKind,
    frontmatter_field_schema,
    input_type_schema,
    validate_frontmatter,
)


def test_field_schema_is_non_empty_and_ordered() -> None:
    fields = frontmatter_field_schema()
    assert fields, "field schema must not be empty"
    assert [field.name for field in fields] == [
        "name",
        "description",
        "tags",
        "input",
        "xprompts",
        "skill",
        "snippet",
    ]
    for field in fields:
        assert field.description, f"{field.name} should have a description"
        assert field.example, f"{field.name} should have an example"
        assert isinstance(field.kind, FrontmatterFieldKind)


def test_structured_and_bool_field_kinds() -> None:
    by_name = {field.name: field for field in frontmatter_field_schema()}
    assert by_name["input"].kind is FrontmatterFieldKind.STRUCTURED
    assert by_name["xprompts"].kind is FrontmatterFieldKind.STRUCTURED
    assert by_name["skill"].kind is FrontmatterFieldKind.BOOL_OR_LIST
    assert by_name["snippet"].kind is FrontmatterFieldKind.BOOL_OR_SCALAR
    assert by_name["skill"].allowed_values


def test_input_type_schema_covers_known_types_with_aliases() -> None:
    types = input_type_schema()
    names = {input_type.name for input_type in types}
    assert {"word", "line", "text", "path", "int", "float", "bool", "code"} <= names
    by_name = {input_type.name: input_type for input_type in types}
    assert "integer" in by_name["int"].aliases
    assert "boolean" in by_name["bool"].aliases
    for input_type in types:
        assert input_type.rule, f"{input_type.name} should have a rule"
        assert input_type.advertised
    internal = input_type_schema(include_internal=True)
    by_internal = {item.name: item for item in internal}
    assert "code" in by_internal
    assert by_internal["code"].advertised is True


def test_validate_frontmatter_accepts_known_good_block() -> None:
    diagnostics = validate_frontmatter(
        "---\ndescription: Refactor the auth module\n"
        "tags: refactor, backend\ninput:\n  service: word\n---\n"
    )
    assert not [d for d in diagnostics if d.is_error], diagnostics


def test_validate_frontmatter_accepts_internal_code_type() -> None:
    diagnostics = validate_frontmatter("---\ninput:\n  script: code\n---\n")
    assert not [d for d in diagnostics if d.is_error], diagnostics


def test_validate_frontmatter_flags_known_bad_value() -> None:
    diagnostics = validate_frontmatter("---\ninput:\n  service: wordd\n---\n")
    codes = {d.code for d in diagnostics}
    assert "invalid_xprompt_frontmatter_input_type" in codes
    offending = next(
        d for d in diagnostics if d.code == "invalid_xprompt_frontmatter_input_type"
    )
    assert offending.is_error


def test_validate_frontmatter_accepts_bare_body_without_delimiters() -> None:
    diagnostics = validate_frontmatter("description: Refactor the auth module")
    assert not [d for d in diagnostics if d.is_error], diagnostics


def test_validate_frontmatter_accepts_log_skill_use_boolean() -> None:
    diagnostics = validate_frontmatter(
        "---\nskill: true\ndescription: Plan helper\nlog_skill_use: false\n---\n"
    )
    assert not [d for d in diagnostics if d.is_error], diagnostics
    codes = {d.code for d in diagnostics}
    assert "unknown_xprompt_frontmatter_field" not in codes, diagnostics


def test_validate_frontmatter_flags_non_boolean_log_skill_use() -> None:
    diagnostics = validate_frontmatter('---\nlog_skill_use: "false"\n---\n')
    codes = {d.code for d in diagnostics}
    assert "invalid_xprompt_frontmatter_log_skill_use" in codes
