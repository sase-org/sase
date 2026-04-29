"""Token-stream snapshots: strings/booleans/escapes and shorthand specials.

Pins token kind/value/position/property-key for the basic and shorthand
subsets of the golden corpus. A future Rust tokenizer must reproduce
these snapshots verbatim.
"""

from __future__ import annotations

from inline_snapshot import snapshot

from tests._query_golden_corpus import (
    GOLDEN_QUERIES_BASIC,
    GOLDEN_QUERIES_SPECIALS,
    token_dicts,
)


def test_token_streams_basic_snapshot() -> None:
    """Token streams for quoted strings, bare words, booleans, escapes."""
    streams = {q: token_dicts(q) for q in GOLDEN_QUERIES_BASIC}
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
        }
    )


def test_token_streams_specials_snapshot() -> None:
    """Token streams for error/running shorthands and standalone forms."""
    streams = {q: token_dicts(q) for q in GOLDEN_QUERIES_SPECIALS}
    assert streams == snapshot(
        {
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
        }
    )
