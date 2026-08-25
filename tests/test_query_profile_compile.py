"""Compiler validation and digest determinism for query profiles."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import (
    ArtifactQuerySchema,
    QueryFieldSpec,
    QueryMacroSpec,
    QueryProfileError,
    QuerySigilSpec,
    compile_query_profile,
    patches_query_schema,
)
from sase.ace.query_profile.registry import HOST_PREDICATES


def _minimal_schema(**overrides: object) -> ArtifactQuerySchema:
    defaults: dict[str, object] = {
        "pane_id": "test",
        "boolean": False,
        "fields": (QueryFieldSpec(key="alpha"),),
    }
    defaults.update(overrides)
    return ArtifactQuerySchema(**defaults)  # type: ignore[arg-type]


def test_compile_rejects_duplicate_field_keys() -> None:
    schema = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="alpha"))
    )
    with pytest.raises(QueryProfileError, match="duplicate field key"):
        compile_query_profile(schema)


def test_compile_rejects_enum_without_static_values() -> None:
    schema = _minimal_schema(fields=(QueryFieldSpec(key="alpha", value_kind="enum"),))
    with pytest.raises(QueryProfileError, match="static_values"):
        compile_query_profile(schema)


def test_compile_rejects_negatable_non_filterable_field() -> None:
    schema = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha", filterable=False, negatable=True),)
    )
    with pytest.raises(QueryProfileError, match="filterable"):
        compile_query_profile(schema)


def test_compile_rejects_non_host_sigil() -> None:
    schema = _minimal_schema(sigils=(QuerySigilSpec(sigil="#", field="alpha"),))
    with pytest.raises(QueryProfileError, match="not a host-recognized sigil"):
        compile_query_profile(schema)


def test_compile_rejects_sigil_targeting_undeclared_field() -> None:
    schema = _minimal_schema(sigils=(QuerySigilSpec(sigil="+", field="missing"),))
    with pytest.raises(QueryProfileError, match="undeclared field"):
        compile_query_profile(schema)


def test_compile_rejects_duplicate_sigil() -> None:
    schema = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="beta")),
        sigils=(
            QuerySigilSpec(sigil="+", field="alpha"),
            QuerySigilSpec(sigil="+", field="beta"),
        ),
    )
    with pytest.raises(QueryProfileError, match="duplicate sigil"):
        compile_query_profile(schema)


def test_compile_rejects_unknown_predicate() -> None:
    schema = _minimal_schema(predicates=("made_up_predicate",))
    with pytest.raises(QueryProfileError, match="unknown predicate"):
        compile_query_profile(schema)


def test_compile_rejects_any_special_without_full_predicate_set() -> None:
    schema = _minimal_schema(predicates=("error_suffix",), any_special=True)
    with pytest.raises(QueryProfileError, match="any_special requires"):
        compile_query_profile(schema)


def test_compile_accepts_any_special_with_full_predicate_set() -> None:
    schema = _minimal_schema(
        predicates=tuple(sorted(HOST_PREDICATES)), any_special=True
    )
    profile = compile_query_profile(schema)
    assert profile.any_special is True


def test_compile_rejects_macro_with_non_host_trigger() -> None:
    schema = _minimal_schema(
        macros=(QueryMacroSpec(trigger="$", letter="d", field="alpha", value="X"),)
    )
    with pytest.raises(QueryProfileError, match="not host-recognized"):
        compile_query_profile(schema)


def test_compile_rejects_macro_targeting_undeclared_field() -> None:
    schema = _minimal_schema(
        macros=(QueryMacroSpec(trigger="%", letter="d", field="missing", value="X"),)
    )
    with pytest.raises(QueryProfileError, match="undeclared"):
        compile_query_profile(schema)


def test_compile_rejects_duplicate_macro() -> None:
    schema = _minimal_schema(
        macros=(
            QueryMacroSpec(trigger="%", letter="d", field="alpha", value="X"),
            QueryMacroSpec(trigger="%", letter="d", field="alpha", value="Y"),
        )
    )
    with pytest.raises(QueryProfileError, match="duplicate macro"):
        compile_query_profile(schema)


def test_digest_is_stable_across_repeated_compiles() -> None:
    schema = patches_query_schema()
    first = compile_query_profile(schema)
    second = compile_query_profile(schema)
    assert first.digest == second.digest
    assert first.to_wire() == second.to_wire()


def test_digest_is_independent_of_authoring_order() -> None:
    forward = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="beta")),
        sigils=(
            QuerySigilSpec(sigil="+", field="alpha"),
            QuerySigilSpec(sigil="^", field="beta"),
        ),
    )
    backward = _minimal_schema(
        fields=(QueryFieldSpec(key="beta"), QueryFieldSpec(key="alpha")),
        sigils=(
            QuerySigilSpec(sigil="^", field="beta"),
            QuerySigilSpec(sigil="+", field="alpha"),
        ),
    )
    assert (
        compile_query_profile(forward).digest == compile_query_profile(backward).digest
    )


def test_digest_changes_when_a_field_is_added() -> None:
    base = compile_query_profile(_minimal_schema())
    grown = compile_query_profile(
        _minimal_schema(
            fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="beta"))
        )
    )
    assert base.digest != grown.digest


def test_digest_changes_when_a_field_flag_changes() -> None:
    base = compile_query_profile(_minimal_schema())
    changed = compile_query_profile(
        _minimal_schema(fields=(QueryFieldSpec(key="alpha", searchable=True),))
    )
    assert base.digest != changed.digest
