"""Rust-routed corpus facade: parse/canonicalize parity with Python."""

from __future__ import annotations

import pytest

from sase.ace.query.profile_reference import (
    canonical_query_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import compile_query_profile
from sase.ace.query_profile.profiles import (
    beads_query_schema,
    files_query_schema,
    patches_query_schema,
    stitches_query_schema,
)
from sase.core.query_profile_corpus_facade import (
    _canonicalize_artifact_query,
    _parse_artifact_query,
)
from tests._query_profile_corpus_facade_helpers import (
    _boolean_value_query_schema,
    _bounds_query_schema,
    _flags_query_schema,
)


@pytest.mark.parametrize(
    "query",
    ['"example"', "%w", "name:example", "!!", "+sase"],
)
def test_parse_and_canonicalize_through_rust_match_python_reference(
    query: str,
) -> None:
    profile = compile_query_profile(patches_query_schema())
    assert _parse_artifact_query(query, profile) == parse_query_for_profile(
        query, profile
    )
    assert _canonicalize_artifact_query(query, profile) == canonical_query_for_profile(
        query, profile
    )


@pytest.mark.parametrize(
    ("query", "flat"),
    [("status:open", True), ("kind:file", False)],
)
def test_flat_parse_and_canonicalize_through_rust_match_python_reference(
    query: str,
    flat: bool,
) -> None:
    profile = compile_query_profile(
        beads_query_schema() if flat else files_query_schema()
    )
    assert _parse_artifact_query(query, profile) == parse_query_for_profile(
        query, profile
    )
    assert _canonicalize_artifact_query(query, profile) == canonical_query_for_profile(
        query, profile
    )


@pytest.mark.parametrize(
    ("schema_builder", "query"),
    [
        (stitches_query_schema, "sidecar"),
        (stitches_query_schema, '"sidecar"'),
        (stitches_query_schema, '-"sidecar"'),
        (stitches_query_schema, "sidecar:true"),
        (_flags_query_schema, "flag"),
        (_flags_query_schema, "-flag"),
        (_flags_query_schema, '"flag"'),
        (_flags_query_schema, '-"flag"'),
        (_bounds_query_schema, "min:5m"),
        (_bounds_query_schema, "max:2h"),
        (_bounds_query_schema, "min:300"),
        (_bounds_query_schema, "exit:300"),
    ],
)
def test_flat_bare_flag_and_bound_key_parse_and_canonicalize_match_python(
    schema_builder,
    query: str,
) -> None:
    profile = compile_query_profile(schema_builder())
    assert _parse_artifact_query(query, profile) == parse_query_for_profile(
        query, profile
    )
    assert _canonicalize_artifact_query(query, profile) == canonical_query_for_profile(
        query, profile
    )


def test_flat_duration_pair_canonicalizes_through_rust_like_python() -> None:
    """AND operand order still follows each parser's emission walk, so parse
    trees can disagree while the cache-key canonical form stays identical.
    """

    profile = compile_query_profile(_bounds_query_schema())
    query = "min:30s max:2h"
    assert _canonicalize_artifact_query(query, profile) == canonical_query_for_profile(
        query, profile
    )


@pytest.mark.parametrize(
    ("query", "canonical"),
    [
        ("name:sase-r8.9.land", "name:sase-r8.9.land"),
        ("name:0b4", "name:0b4"),
        ("name:001--2", "name:001--2"),
        ("family:research.12", "family:research.12"),
        ("min:5m", "min:300"),
        ("attempt:002", "attempt:2"),
        ("9lives", '"9lives"'),
    ],
)
def test_boolean_widened_values_parse_and_canonicalize_through_rust_like_python(
    query: str, canonical: str
) -> None:
    profile = compile_query_profile(_boolean_value_query_schema())

    assert canonical_query_for_profile(query, profile) == canonical
    assert _parse_artifact_query(query, profile) == parse_query_for_profile(
        query, profile
    )
    assert _canonicalize_artifact_query(query, profile) == canonical
    assert _canonicalize_artifact_query(query, profile) == canonical_query_for_profile(
        query, profile
    )
