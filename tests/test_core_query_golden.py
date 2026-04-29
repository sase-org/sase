"""Golden contract tests for the query language (Phase 2A, sase-17.1).

Pins token streams, AST/canonical-string output, evaluation results, and
selected error messages for a corpus of queries that covers every shape the
language can produce. A future Rust implementation must reproduce these
snapshots — until then the snapshots also pin the Python tokenizer/parser/
evaluator's behavior so refactors can't drift silently.

Regex semantics inventory
-------------------------

The query language is **substring matching only**. Quoted strings and bare
words match if the literal characters appear anywhere in the searchable
text (case-insensitive by default; case-sensitive with the ``c"..."``
prefix). The two ``re`` patterns in
:mod:`sase.ace.query.evaluator` (``_WORKSPACE_SUFFIX_RE`` /
``_LEGACY_READY_TO_MAIL_RE``) are private status-suffix strippers — they
are never given user input. The Rust port must NOT introduce a regex engine
for user queries.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest
from inline_snapshot import snapshot

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.parser import QueryParseError, parse_query_python
from sase.ace.query.tokenizer import tokenize
from sase.ace.query.types import to_canonical_string
from sase.core import parser_facade, query_facade
from sase.core.query_wire import (
    QUERY_WIRE_SCHEMA_VERSION,
    QueryErrorWire,
    query_wire_to_json_dict,
)
from sase.core.query_wire_conversion import (
    build_query_program_wire,
    query_expr_from_wire,
    query_expr_to_wire,
    token_from_wire,
    token_to_wire,
)

_CORPUS_DIR = Path(__file__).parent / "core_golden"
_PROJECT_GP = _CORPUS_DIR / "myproj.gp"


def _load() -> list[ChangeSpec]:
    return parser_facade.parse_project_file(str(_PROJECT_GP))


def _token_dicts(query: str) -> list[dict]:
    return [query_wire_to_json_dict(token_to_wire(t)) for t in tokenize(query)]


def _canonical(query: str) -> str:
    return to_canonical_string(parse_query_python(query))


# Single source of truth for the parse/eval golden matrix. Keeping it as a
# module-level list makes it easy for the benchmark harness to import.
GOLDEN_QUERIES: list[str] = [
    # ---- quoted strings and case sensitivity
    '"alpha"',
    'c"Alpha"',
    '"feature"',
    # ---- bare words and implicit AND
    "alpha",
    '"alpha" "beta"',
    # ---- explicit boolean operators and parens
    '"alpha" AND "beta"',
    '"alpha" OR "beta"',
    'NOT "beta"',
    '("alpha" OR "beta") AND "feature"',
    # ---- escapes inside quoted strings
    r'"foo\\bar"',
    r'"line\nbreak"',
    # ---- error/running shorthands and standalone forms
    "!!!",
    "!",
    "@@@",
    "@",
    "$$$",
    "$",
    "*",
    "!!",
    "!@",
    "!$",
    # ---- property filters: long forms
    "status:Ready",
    "status:Reverted OR status:Submitted",
    "project:myproj",
    "ancestor:alpha",
    "name:beta",
    "sibling:beta",
    'ancestor:alpha AND NOT "beta"',
    # ---- shorthand forms for properties
    "%d",
    "%m",
    "%r",
    "%s",
    "%w",
    "%y",
    "+myproj",
    "^alpha",
    "~beta",
    "&beta",
]


def test_token_streams_snapshot() -> None:
    """Pin token kind/value/position/property-key for every corpus query."""
    streams = {q: _token_dicts(q) for q in GOLDEN_QUERIES}
    assert streams == snapshot(
        {
            '"alpha"': [
                {
                    "kind": "string",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 7,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            'c"Alpha"': [
                {
                    "kind": "string",
                    "value": "Alpha",
                    "position": 1,
                    "case_sensitive": True,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 8,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            '"feature"': [
                {
                    "kind": "string",
                    "value": "feature",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 9,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "alpha": [
                {
                    "kind": "string",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 5,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            '"alpha" "beta"': [
                {
                    "kind": "string",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "beta",
                    "position": 8,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 14,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            '"alpha" AND "beta"': [
                {
                    "kind": "string",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "and",
                    "value": "AND",
                    "position": 8,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "beta",
                    "position": 12,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 18,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            '"alpha" OR "beta"': [
                {
                    "kind": "string",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "or",
                    "value": "OR",
                    "position": 8,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "beta",
                    "position": 11,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 17,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            'NOT "beta"': [
                {
                    "kind": "not",
                    "value": "NOT",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "beta",
                    "position": 4,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 10,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            '("alpha" OR "beta") AND "feature"': [
                {
                    "kind": "lparen",
                    "value": "(",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "alpha",
                    "position": 1,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "or",
                    "value": "OR",
                    "position": 9,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "beta",
                    "position": 12,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "rparen",
                    "value": ")",
                    "position": 18,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "and",
                    "value": "AND",
                    "position": 20,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "feature",
                    "position": 24,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 33,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            r'"foo\\bar"': [
                {
                    "kind": "string",
                    "value": "foo\\bar",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 10,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            r'"line\nbreak"': [
                {
                    "kind": "string",
                    "value": "line\nbreak",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 13,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "!!!": [
                {
                    "kind": "error_suffix",
                    "value": "!!!",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 3,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "!": [
                {
                    "kind": "error_suffix",
                    "value": "!",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 1,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "@@@": [
                {
                    "kind": "running_agent",
                    "value": "@@@",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 3,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "@": [
                {
                    "kind": "running_agent",
                    "value": "@",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 1,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "$$$": [
                {
                    "kind": "running_process",
                    "value": "$$$",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 3,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "$": [
                {
                    "kind": "running_process",
                    "value": "$",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 1,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "*": [
                {
                    "kind": "any_special",
                    "value": "*",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 1,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "!!": [
                {
                    "kind": "not_error_suffix",
                    "value": "!!",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "!@": [
                {
                    "kind": "not_running_agent",
                    "value": "!@",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "!$": [
                {
                    "kind": "not_running_process",
                    "value": "!$",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "status:Ready": [
                {
                    "kind": "property",
                    "value": "Ready",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 12,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "status:Reverted OR status:Submitted": [
                {
                    "kind": "property",
                    "value": "Reverted",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "or",
                    "value": "OR",
                    "position": 16,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "property",
                    "value": "Submitted",
                    "position": 19,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 35,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "project:myproj": [
                {
                    "kind": "property",
                    "value": "myproj",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "project",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 14,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "ancestor:alpha": [
                {
                    "kind": "property",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "ancestor",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 14,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "name:beta": [
                {
                    "kind": "property",
                    "value": "beta",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "name",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 9,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "sibling:beta": [
                {
                    "kind": "property",
                    "value": "beta",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "sibling",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 12,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            'ancestor:alpha AND NOT "beta"': [
                {
                    "kind": "property",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "ancestor",
                },
                {
                    "kind": "and",
                    "value": "AND",
                    "position": 15,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "not",
                    "value": "NOT",
                    "position": 19,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "string",
                    "value": "beta",
                    "position": 23,
                    "case_sensitive": False,
                    "property_key": None,
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 29,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "%d": [
                {
                    "kind": "property",
                    "value": "DRAFT",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "%m": [
                {
                    "kind": "property",
                    "value": "MAILED",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "%r": [
                {
                    "kind": "property",
                    "value": "REVERTED",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "%s": [
                {
                    "kind": "property",
                    "value": "SUBMITTED",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "%w": [
                {
                    "kind": "property",
                    "value": "WIP",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "%y": [
                {
                    "kind": "property",
                    "value": "READY",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "status",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 2,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "+myproj": [
                {
                    "kind": "property",
                    "value": "myproj",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "project",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 7,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "^alpha": [
                {
                    "kind": "property",
                    "value": "alpha",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "ancestor",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 6,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "~beta": [
                {
                    "kind": "property",
                    "value": "beta",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "sibling",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 5,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
            "&beta": [
                {
                    "kind": "property",
                    "value": "beta",
                    "position": 0,
                    "case_sensitive": False,
                    "property_key": "name",
                },
                {
                    "kind": "eof",
                    "value": "",
                    "position": 5,
                    "case_sensitive": False,
                    "property_key": None,
                },
            ],
        }
    )


def test_canonical_form_snapshot() -> None:
    """The canonical-form string is the contract Phase 2B's parser must hit."""
    canonical = {q: _canonical(q) for q in GOLDEN_QUERIES}
    assert canonical == snapshot(
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
    specs = _load()
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


# Malformed queries — the messages here are user-visible (the TUI surfaces
# them in the query bar). Pin both the position and message text so a Rust
# port produces the same diagnostics.
_MALFORMED_QUERIES: list[str] = [
    "",
    '"unterminated',
    '"\\x"',
    "AND",
    "(",
    ")",
    "alpha AND",
    "%q",
    "+",
    "+1abc",
    "unknown:value",
    "@bad",
    "$bad",
    "*bad",
]


def test_malformed_query_messages_snapshot() -> None:
    """Pin user-visible parser/tokenizer errors for malformed input.

    The shape mirrors :class:`QueryErrorWire` (kind/message/position) so a
    Rust port can reuse the same fixtures via JSON.
    """
    errors: dict[str, dict[str, object]] = {}
    for q in _MALFORMED_QUERIES:
        with pytest.raises(QueryParseError) as exc:
            parse_query_python(q)
        wire_error = QueryErrorWire(
            kind="parse_error",
            message=str(exc.value),
            position=exc.value.position,
        )
        errors[q] = {
            "position": wire_error.position,
            "message": wire_error.message,
        }
    assert errors == snapshot(
        {
            "": {"position": 0, "message": "Empty query (at position 0)"},
            '"unterminated': {
                "position": 0,
                "message": "Unterminated string at position 0 (at position 0)",
            },
            '"\\x"': {
                "position": 1,
                "message": "Invalid escape sequence: \\x at position 1 (at position 1)",
            },
            "AND": {
                "position": 0,
                "message": "Expected string or '(', got AND (at position 0)",
            },
            "(": {
                "position": 1,
                "message": "Expected string or '(', got EOF (at position 1)",
            },
            ")": {
                "position": 0,
                "message": "Expected string or '(', got ) (at position 0)",
            },
            "alpha AND": {
                "position": 9,
                "message": "Expected string or '(', got EOF (at position 9)",
            },
            "%q": {
                "position": 0,
                "message": "Invalid status shorthand (use %d, %m, %r, %s, %w, or %y) at position 0 (at position 0)",
            },
            "+": {
                "position": 0,
                "message": "Expected project name after '+' at position 0 (at position 0)",
            },
            "+1abc": {
                "position": 0,
                "message": "Expected project name after '+' at position 0 (at position 0)",
            },
            "unknown:value": {
                "position": 0,
                "message": "Unknown property key: unknown (valid keys: status, project, ancestor, name, sibling) at position 0 (at position 0)",
            },
            "@bad": {
                "position": 0,
                "message": "Unexpected character: @ at position 0 (at position 0)",
            },
            "$bad": {
                "position": 0,
                "message": "Unexpected character: $ at position 0 (at position 0)",
            },
            "*bad": {
                "position": 0,
                "message": "Unexpected character: * at position 0 (at position 0)",
            },
        }
    )


def test_query_program_wire_round_trip() -> None:
    """``query_expr_from_wire(query_expr_to_wire(x))`` must round-trip."""
    for q in GOLDEN_QUERIES:
        expr = parse_query_python(q)
        wire = query_expr_to_wire(expr)
        rebuilt = query_expr_from_wire(wire)
        # AST round-trip equality via canonical string (the AST dataclasses
        # are not hashable, so we compare on the canonical form which is the
        # contract callers care about).
        assert to_canonical_string(rebuilt) == to_canonical_string(expr), q


def test_token_wire_round_trip() -> None:
    """Token wire conversion is invertible for every corpus query."""
    for q in GOLDEN_QUERIES:
        for original in tokenize(q):
            wire = token_to_wire(original)
            rebuilt = token_from_wire(wire)
            assert rebuilt == original, q


def test_query_program_wire_snapshot() -> None:
    """A representative ``QueryProgramWire`` for parity comparison.

    We pick one query that exercises every shape (string, property, NOT, AND,
    OR, parens) so the JSON shape is locked down without bloating the
    snapshot file.
    """
    q = '("alpha" OR "beta") AND NOT status:Submitted'
    program = build_query_program_wire(q, parse_query_python(q))
    assert query_wire_to_json_dict(program) == snapshot(
        {
            "schema_version": QUERY_WIRE_SCHEMA_VERSION,
            "source": '("alpha" OR "beta") AND NOT status:Submitted',
            "canonical": '("alpha" OR "beta") AND NOT status:Submitted',
            "ast": {
                "kind": "and",
                "value": "",
                "case_sensitive": False,
                "is_error_suffix": False,
                "is_running_agent": False,
                "is_running_process": False,
                "property_key": None,
                "operands": (
                    {
                        "kind": "or",
                        "value": "",
                        "case_sensitive": False,
                        "is_error_suffix": False,
                        "is_running_agent": False,
                        "is_running_process": False,
                        "property_key": None,
                        "operands": (
                            {
                                "kind": "string",
                                "value": "alpha",
                                "case_sensitive": False,
                                "is_error_suffix": False,
                                "is_running_agent": False,
                                "is_running_process": False,
                                "property_key": None,
                                "operands": (),
                            },
                            {
                                "kind": "string",
                                "value": "beta",
                                "case_sensitive": False,
                                "is_error_suffix": False,
                                "is_running_agent": False,
                                "is_running_process": False,
                                "property_key": None,
                                "operands": (),
                            },
                        ),
                    },
                    {
                        "kind": "not",
                        "value": "",
                        "case_sensitive": False,
                        "is_error_suffix": False,
                        "is_running_agent": False,
                        "is_running_process": False,
                        "property_key": None,
                        "operands": (
                            {
                                "kind": "property",
                                "value": "Submitted",
                                "case_sensitive": False,
                                "is_error_suffix": False,
                                "is_running_agent": False,
                                "is_running_process": False,
                                "property_key": "status",
                                "operands": (),
                            },
                        ),
                    },
                ),
            },
        }
    )


def test_substring_semantics_not_regex() -> None:
    """Quoted-string semantics are substring matching, not regex.

    Phase 2B/2C must not introduce a regex engine for user input; the
    Python evaluator passes raw strings into ``in`` after lowercasing.
    """
    specs = _load()
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


def _names(matched: Iterable[ChangeSpec]) -> list[str]:
    return [cs.name for cs in matched]


def test_facade_and_python_eval_agree() -> None:
    """The facade route and direct Python route must agree on the corpus.

    Phase 2A's job is to lock this in before any Rust implementation lands;
    Phase 2D will add a third column for the Rust route.
    """
    specs = _load()
    ctx = query_facade.build_query_context(specs)
    for q in GOLDEN_QUERIES:
        expr = parse_query_python(q)
        via_facade = _names(
            cs
            for cs in specs
            if query_facade.evaluate_query_with_context(expr, cs, ctx)
        )
        via_python = _names(
            cs for cs in specs if query_facade.evaluate_query(expr, cs, specs)
        )
        assert via_facade == via_python, q
