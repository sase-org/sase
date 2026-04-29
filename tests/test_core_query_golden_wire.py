"""Wire round-trips and the representative ``QueryProgramWire`` snapshot."""

from __future__ import annotations

from inline_snapshot import snapshot

from sase.ace.query.parser import parse_query_python
from sase.ace.query.tokenizer import tokenize
from sase.ace.query.types import to_canonical_string
from sase.core.query_wire import QUERY_WIRE_SCHEMA_VERSION, query_wire_to_json_dict
from sase.core.query_wire_conversion import (
    build_query_program_wire,
    query_expr_from_wire,
    query_expr_to_wire,
    token_from_wire,
    token_to_wire,
)

from tests._query_golden_corpus import GOLDEN_QUERIES


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
