"""Canonical-form, evaluation matrix, and facade-vs-Python parity tests."""

from __future__ import annotations

from inline_snapshot import snapshot

from sase.ace.query.parser import parse_query_python
from sase.core import query_facade

from tests._query_golden_corpus import (
    GOLDEN_QUERIES,
    canonical,
    load_specs,
    names,
)


def test_canonical_form_snapshot() -> None:
    """The canonical-form string is the contract Phase 2B's parser must hit."""
    out = {q: canonical(q) for q in GOLDEN_QUERIES}
    assert out == snapshot(
        {
            '"alpha"': '"alpha"',
            'c"Alpha"': 'c"Alpha"',
            '"feature"': '"feature"',
            "alpha": '"alpha"',
            '"alpha" "beta"': '"alpha" AND "beta"',
            '"alpha" AND "beta"': '"alpha" AND "beta"',
            '"alpha" OR "beta"': '"alpha" OR "beta"',
            'NOT "beta"': 'NOT "beta"',
            '("alpha" OR "beta") AND "feature"': '("alpha" OR "beta") AND "feature"',
            r'"foo\\bar"': r'"foo\\bar"',
            r'"line\nbreak"': r'"line\nbreak"',
            "!!!": "!!!",
            "!": "!!!",
            "@@@": "@@@",
            "@": "@@@",
            "$$$": "$$$",
            "$": "$$$",
            "*": "!!! OR @@@ OR $$$",
            "!!": "NOT !!!",
            "!@": "NOT @@@",
            "!$": "NOT $$$",
            "status:Ready": "status:Ready",
            "status:Reverted OR status:Submitted": "status:Reverted OR status:Submitted",
            "project:myproj": "project:myproj",
            "ancestor:alpha": "ancestor:alpha",
            "name:beta": "name:beta",
            "sibling:beta": "sibling:beta",
            'ancestor:alpha AND NOT "beta"': 'ancestor:alpha AND NOT "beta"',
            "%d": "status:DRAFT",
            "%m": "status:MAILED",
            "%r": "status:REVERTED",
            "%s": "status:SUBMITTED",
            "%w": "status:WIP",
            "%y": "status:READY",
            "+myproj": "project:myproj",
            "^alpha": "ancestor:alpha",
            "~beta": "sibling:beta",
            "&beta": "name:beta",
        }
    )


def test_evaluation_matrix_snapshot() -> None:
    """Evaluating each corpus query against the corpus yields a stable matrix.

    For property/string-only queries we use the project corpus directly; for
    the running-agent shorthand we rely on ``gamma``'s RUNNING hook. The
    error-suffix shorthand fires on ``alpha`` (it has an unresolved comment
    suffix).
    """
    specs = load_specs()
    ctx = query_facade.build_query_context(specs)
    matrix: dict[str, list[str]] = {}
    for q in GOLDEN_QUERIES:
        expr = parse_query_python(q)
        matrix[q] = [
            cs.name
            for cs in specs
            if query_facade.evaluate_query_with_context(expr, cs, ctx)
        ]
    assert matrix == snapshot(
        {
            '"alpha"': ["alpha", "beta", "beta__260102_010101"],
            'c"Alpha"': [],
            '"feature"': ["alpha", "beta", "gamma"],
            "alpha": ["alpha", "beta", "beta__260102_010101"],
            '"alpha" "beta"': ["beta", "beta__260102_010101"],
            '"alpha" AND "beta"': ["beta", "beta__260102_010101"],
            '"alpha" OR "beta"': ["alpha", "beta", "beta__260102_010101"],
            'NOT "beta"': ["alpha", "gamma"],
            '("alpha" OR "beta") AND "feature"': ["alpha", "beta"],
            r'"foo\\bar"': [],
            r'"line\nbreak"': [],
            "!!!": ["alpha"],
            "!": ["alpha"],
            "@@@": ["gamma"],
            "@": ["gamma"],
            "$$$": [],
            "$": [],
            "*": ["alpha", "gamma"],
            "!!": ["beta", "beta__260102_010101", "gamma"],
            "!@": ["alpha", "beta", "beta__260102_010101"],
            "!$": [
                "alpha",
                "beta",
                "beta__260102_010101",
                "gamma",
            ],
            "status:Ready": ["gamma"],
            "status:Reverted OR status:Submitted": [
                "alpha",
                "beta__260102_010101",
            ],
            "project:myproj": [],
            "ancestor:alpha": ["alpha", "beta", "beta__260102_010101"],
            "name:beta": ["beta"],
            "sibling:beta": ["beta"],
            'ancestor:alpha AND NOT "beta"': ["alpha"],
            "%d": [],
            "%m": [],
            "%r": ["beta__260102_010101"],
            "%s": ["alpha"],
            "%w": ["beta"],
            "%y": ["gamma"],
            "+myproj": [],
            "^alpha": ["alpha", "beta", "beta__260102_010101"],
            "~beta": ["beta"],
            "&beta": ["beta"],
        }
    )


def test_substring_semantics_not_regex() -> None:
    """Quoted-string semantics are substring matching, not regex.

    Phase 2B/2C must not introduce a regex engine for user input; the
    Python evaluator passes raw strings into ``in`` after lowercasing.
    """
    specs = load_specs()
    ctx = query_facade.build_query_context(specs)
    # ``.*`` is not a wildcard — it would only match if the literal ``.*``
    # appeared in the searchable text, which it does not.
    expr = parse_query_python('".*"')
    assert all(
        not query_facade.evaluate_query_with_context(expr, cs, ctx) for cs in specs
    )
    # Backslashes are taken literally outside the documented escape set.
    expr = parse_query_python(r'"foo\\bar"')
    assert all(
        not query_facade.evaluate_query_with_context(expr, cs, ctx) for cs in specs
    )


def test_facade_and_python_eval_agree() -> None:
    """The facade route and direct Python route must agree on the corpus.

    Phase 2A's job is to lock this in before any Rust implementation lands;
    Phase 2D will add a third column for the Rust route.
    """
    specs = load_specs()
    ctx = query_facade.build_query_context(specs)
    for q in GOLDEN_QUERIES:
        expr = parse_query_python(q)
        via_facade = names(
            cs
            for cs in specs
            if query_facade.evaluate_query_with_context(expr, cs, ctx)
        )
        via_python = names(
            cs for cs in specs if query_facade.evaluate_query(expr, cs, specs)
        )
        assert via_facade == via_python, q
