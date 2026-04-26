"""Round-trip tests for the agent query language canonicalizer.

For each query in the corpus we assert::

    parse(query)                -> ast1
    to_canonical_string(ast1)   -> canon
    parse(canon)                -> ast2
    ast1 == ast2

So canonicalization is a normalization fixed-point: the canonical form of a
query parses back to the same AST.
"""

import pytest
from sase.ace.agent_query import parse_agent_query, to_canonical_string


CORPUS = [
    # Atoms
    "foo",
    '"hello world"',
    'c"FAILED"',
    # Property matches across the closed allowlist
    "status:failed",
    "cl:my-cl",
    "project:foo",
    "name:bar",
    "model:opus",
    "provider:anthropic",
    "tag:pinned",
    "type:workflow",
    "source:axe",
    "source:manual",
    "needs:input",
    "pinned:true",
    "hidden:false",
    "attention:true",
    "text:foo",
    # Age comparisons
    "age>2h",
    "age<30m",
    "age>=1d",
    "age<=15s",
    "age=1h",
    "age:2h",  # alias for age>=2h
    # Boolean composition
    "a AND b",
    "a OR b",
    "NOT a",
    "NOT (a OR b)",
    "(a OR b) AND c",
    # Mixed
    '"database migration" status:failed',
    "status:failed AND attention:true AND age>2h",
    "NOT (project:foo OR cl:bar)",
]


@pytest.mark.parametrize("query", CORPUS)
def test_canonicalization_round_trip(query: str) -> None:
    ast1 = parse_agent_query(query)
    canon = to_canonical_string(ast1)
    ast2 = parse_agent_query(canon)
    assert ast1 == ast2, f"round-trip failed for {query!r}: canon={canon!r}"


def test_canonical_form_is_idempotent() -> None:
    # Canonicalizing twice produces the same string.
    for query in CORPUS:
        first = to_canonical_string(parse_agent_query(query))
        second = to_canonical_string(parse_agent_query(first))
        assert first == second


def test_age_alias_canonicalizes_to_explicit_ge() -> None:
    # `age:2h` is sugar; the canonical form spells the comparator.
    assert to_canonical_string(parse_agent_query("age:2h")) == "age>=2h"


def test_bare_word_canonicalizes_to_quoted() -> None:
    assert to_canonical_string(parse_agent_query("foo")) == '"foo"'


def test_implicit_and_canonicalizes_to_explicit() -> None:
    assert to_canonical_string(parse_agent_query("a b")) == '"a" AND "b"'
