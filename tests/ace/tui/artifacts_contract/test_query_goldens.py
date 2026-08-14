"""Frozen Patch query oracle: precedence, quoting, sigils, and errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.query.parser import QueryParseError, _parse_query_python
from sase.core import query_facade
from sase.core.query_wire import QueryErrorWire

from tests._query_golden_corpus import canonical, load_specs

_GOLDEN = Path(__file__).resolve().parent / "goldens" / "query" / "cases.json"


def _cases() -> dict[str, object]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_query_canonical_forms_match_frozen_patch_oracle() -> None:
    golden = _cases()["canonical"]
    assert isinstance(golden, dict)
    assert {query: canonical(query) for query in golden} == golden


def test_query_selection_results_match_frozen_patch_oracle() -> None:
    golden = _cases()["evaluation"]
    assert isinstance(golden, dict)
    specs = load_specs()
    ctx = query_facade.build_query_context(specs)
    live: dict[str, list[str]] = {}
    for query in golden:
        expr = _parse_query_python(query)
        live[query] = [
            spec.name
            for spec in specs
            if query_facade.evaluate_query_with_context(expr, spec, ctx)
        ]
    assert live == golden


def test_invalid_query_messages_match_frozen_patch_oracle() -> None:
    golden = _cases()["errors"]
    assert isinstance(golden, dict)
    live: dict[str, dict[str, object]] = {}
    for query in golden:
        with pytest.raises(QueryParseError) as exc:
            _parse_query_python(query)
        wire = QueryErrorWire(
            kind="parse_error",
            message=str(exc.value),
            position=exc.value.position,
        )
        live[query] = {"position": wire.position, "message": wire.message}
    assert live == golden
