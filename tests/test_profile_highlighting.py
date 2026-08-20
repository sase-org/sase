"""Profile-driven query syntax highlighting."""

from __future__ import annotations

import pytest

from sase.ace.query.profile_highlighting import (
    _classify_flat_query_tokens,
    highlight_query,
)
from sase.ace.query_profile import (
    ArtifactQuerySchema,
    QueryFieldSpec,
    QueryMacroSpec,
    QuerySigilSpec,
    compile_query_profile,
)
from sase.ace.query_profile.profiles import beads_query_schema, patches_query_schema

_BEADS_PROFILE = compile_query_profile(beads_query_schema())
_PATCHES_PROFILE = compile_query_profile(patches_query_schema())

_SIGIL_MACRO_PROFILE = compile_query_profile(
    ArtifactQuerySchema(
        pane_id="test-flat-shorthand",
        boolean=False,
        fields=(
            QueryFieldSpec(key="project", filterable=True, negatable=True),
            QueryFieldSpec(key="status", filterable=True, negatable=True),
        ),
        sigils=(QuerySigilSpec("+", "project"),),
        macros=(QueryMacroSpec("%", "d", "status", "done"),),
        predicates=(),
        any_special=False,
        free_text_hint="free text",
    )
)


def test_known_key() -> None:
    assert _classify_flat_query_tokens("status:closed", _BEADS_PROFILE) == [
        ("status:", "property_key"),
        ("closed", "property_value"),
    ]


def test_host_owned_limit_highlights_as_a_known_key() -> None:
    assert _classify_flat_query_tokens("limit:100", _BEADS_PROFILE) == [
        ("limit:", "property_key"),
        ("100", "property_value"),
    ]


def test_unknown_key() -> None:
    assert _classify_flat_query_tokens("bogus:x", _BEADS_PROFILE) == [
        ("bogus:", "unknown_key"),
        ("x", "property_value"),
    ]


def test_search_only_field_renders_as_unknown_key() -> None:
    # "id" is searchable but not filterable in the Beads profile, so
    # `id:value` is invalid per the real parser too.
    assert _classify_flat_query_tokens("id:5", _BEADS_PROFILE) == [
        ("id:", "unknown_key"),
        ("5", "property_value"),
    ]


def test_negated_key() -> None:
    assert _classify_flat_query_tokens("-status:closed", _BEADS_PROFILE) == [
        ("-", "negation"),
        ("status:", "property_key"),
        ("closed", "property_value"),
    ]


def test_quoted_value() -> None:
    assert _classify_flat_query_tokens('assignee:"Bryan Bugyi"', _BEADS_PROFILE) == [
        ("assignee:", "property_key"),
        ('"Bryan Bugyi"', "quoted"),
    ]


def test_comma_repeated_value() -> None:
    assert _classify_flat_query_tokens("type:bug,feature", _BEADS_PROFILE) == [
        ("type:", "property_key"),
        ("bug,feature", "property_value"),
    ]


@pytest.mark.parametrize(
    ("text", "style"),
    [
        ("!!!", "error_suffix"),
        ("!!", "error_suffix"),
        ("!", "error_suffix"),
        ("@@@", "running_agent"),
        ("!@", "running_agent"),
        ("@", "running_agent"),
        ("$$$", "running_process"),
        ("!$", "running_process"),
        ("$", "running_process"),
    ],
)
def test_predicate(text: str, style: str) -> None:
    assert _classify_flat_query_tokens(text, _BEADS_PROFILE) == [(text, style)]


def test_any_special() -> None:
    assert _classify_flat_query_tokens("*", _BEADS_PROFILE) == [("*", "any_special")]


def test_predicate_absent_from_profile_renders_as_term() -> None:
    no_predicate_profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="test-no-predicates",
            boolean=False,
            fields=(QueryFieldSpec(key="status", filterable=True),),
            predicates=(),
            any_special=False,
        )
    )
    assert _classify_flat_query_tokens("!!!", no_predicate_profile) == [("!!!", "term")]


def test_bare_term() -> None:
    assert _classify_flat_query_tokens("hello", _BEADS_PROFILE) == [("hello", "term")]


def test_quoted_free_text() -> None:
    assert _classify_flat_query_tokens('"hello world"', _BEADS_PROFILE) == [
        ('"hello world"', "quoted")
    ]


def test_empty_string() -> None:
    assert _classify_flat_query_tokens("", _BEADS_PROFILE) == []


def test_half_typed_key_only_token() -> None:
    assert _classify_flat_query_tokens("status:", _BEADS_PROFILE) == [
        ("status:", "property_key")
    ]


def test_sigil() -> None:
    assert _classify_flat_query_tokens("+myproj", _SIGIL_MACRO_PROFILE) == [
        ("+myproj", "shorthand")
    ]


def test_macro() -> None:
    assert _classify_flat_query_tokens("%d", _SIGIL_MACRO_PROFILE) == [
        ("%d", "shorthand")
    ]


def test_whitespace_preserved_between_tokens() -> None:
    assert _classify_flat_query_tokens("status:open  hello", _BEADS_PROFILE) == [
        ("status:", "property_key"),
        ("open", "property_value"),
        ("  ", "whitespace"),
        ("hello", "term"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "status:",
        'title:"unterminated',
        "-",
        "--",
        ":::",
        '"""',
        "status:closed AND (bogus",
        "\\" * 5,
        "status:closed,,,",
    ],
)
def test_classify_never_raises(text: str) -> None:
    _classify_flat_query_tokens(text, _BEADS_PROFILE)  # must not raise
    highlight_query(text, _BEADS_PROFILE)  # must not raise
    highlight_query(text, _PATCHES_PROFILE)  # must not raise (boolean dialect)


def test_highlight_query_boolean_dialect_reuses_existing_tokenizer() -> None:
    rendered = highlight_query("status:closed", _PATCHES_PROFILE)
    assert rendered.plain == "status:closed"
    assert rendered.spans


def test_highlight_query_flat_dialect_renders_full_text() -> None:
    rendered = highlight_query("-status:closed hello", _BEADS_PROFILE)
    assert rendered.plain == "-status:closed hello"
