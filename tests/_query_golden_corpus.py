"""Shared fixtures for the query-language golden contract tests.

The corpus is split across several ``test_core_query_golden_*.py`` modules
to keep individual snapshot blocks small. This module is the single source
of truth for the query corpus and the helper functions those tests share;
keeping the corpus list at module level also makes it easy for the
benchmark harness in ``tests/perf/`` to import.

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

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.parser import _parse_query_python
from sase.ace.query.tokenizer import tokenize
from sase.ace.query.types import to_canonical_string
from sase.core import parser_facade
from sase.core.query_wire import query_wire_to_json_dict
from sase.core.query_wire_conversion import token_to_wire

_CORPUS_DIR = Path(__file__).parent / "core_golden"
PROJECT_GP = _CORPUS_DIR / "myproj.gp"


# Subsets are used by per-category snapshot tests; the concatenated
# ``GOLDEN_QUERIES`` list is the matrix all other tests iterate over.
GOLDEN_QUERIES_BASIC: list[str] = [
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
]

GOLDEN_QUERIES_SPECIALS: list[str] = [
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
]

GOLDEN_QUERIES_PROPERTIES: list[str] = [
    # ---- property filters: long forms
    "status:Ready",
    "status:Reverted OR status:Submitted",
    "project:myproj",
    "ancestor:alpha",
    "name:beta",
    "sibling:beta",
    'ancestor:alpha AND NOT "beta"',
]

GOLDEN_QUERIES_PROPERTY_SHORTHAND: list[str] = [
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

GOLDEN_QUERIES: list[str] = (
    GOLDEN_QUERIES_BASIC
    + GOLDEN_QUERIES_SPECIALS
    + GOLDEN_QUERIES_PROPERTIES
    + GOLDEN_QUERIES_PROPERTY_SHORTHAND
)


# Malformed queries — the messages here are user-visible (the TUI surfaces
# them in the query bar). Pinned in test_core_query_golden_errors.py.
MALFORMED_QUERIES: list[str] = [
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


def load_specs() -> list[ChangeSpec]:
    return parser_facade.parse_project_file(str(PROJECT_GP))


def token_dicts(query: str) -> list[dict]:
    return [query_wire_to_json_dict(token_to_wire(t)) for t in tokenize(query)]


def canonical(query: str) -> str:
    return to_canonical_string(_parse_query_python(query))


def names(matched: Iterable[ChangeSpec]) -> list[str]:
    return [cs.name for cs in matched]
