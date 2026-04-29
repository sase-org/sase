"""Token-stream snapshots: property filters (long form + shorthand).

Pins token kind/value/position/property-key for the property-filter subset
of the golden corpus. A future Rust tokenizer must reproduce these
snapshots verbatim.
"""

from __future__ import annotations

from inline_snapshot import snapshot

from tests._query_golden_corpus import (
    GOLDEN_QUERIES_PROPERTIES,
    GOLDEN_QUERIES_PROPERTY_SHORTHAND,
    token_dicts,
)


def test_token_streams_properties_snapshot() -> None:
    """Token streams for long-form property filters (``key:value``)."""
    streams = {q: token_dicts(q) for q in GOLDEN_QUERIES_PROPERTIES}
    assert streams == snapshot(
        {
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
        }
    )


def test_token_streams_property_shorthand_snapshot() -> None:
    """Token streams for property shorthands (``%`` / ``+`` / ``^`` / ``~`` / ``&``)."""
    streams = {q: token_dicts(q) for q in GOLDEN_QUERIES_PROPERTY_SHORTHAND}
    assert streams == snapshot(
        {
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
