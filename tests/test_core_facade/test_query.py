"""Tests for ``sase.core.query_facade``.

Phase 8D rewired :func:`sase.core.query_facade.parse_query` to call
``sase_core_rs`` directly through
:func:`sase.core.rust.require_rust_binding`. After Phase 8F there is no
``dispatch`` layer left: the unported entry points (per-row evaluators,
``build_query_context``, the deferred ``evaluate_query_many`` batch path)
call their Python implementations directly without consulting any
backend env var.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.ace.query import evaluator as raw_evaluator
from sase.ace.query.parser import parse_query_python as raw_parse_query
from sase.core import parser_facade, query_facade
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from tests.test_core_facade._helpers import install_fake_query_module


def test_query_parse_and_evaluate_match_python(
    sample_project: Path,
) -> None:
    specs = parser_facade.parse_project_file(str(sample_project))
    via_facade = query_facade.parse_query('"example"')
    direct = raw_parse_query('"example"')
    # parse_query returns a dataclass tree; their .__class__ and .value
    # should match.
    assert type(via_facade) is type(direct)

    ctx = query_facade.build_query_context(specs)
    direct_ctx = raw_evaluator.build_query_context(specs)
    assert set(ctx.name_map.keys()) == set(direct_ctx.name_map.keys())

    for cs in specs:
        expected = raw_evaluator.evaluate_query(direct, cs, specs)
        assert query_facade.evaluate_query(via_facade, cs, specs) == expected
        assert query_facade.evaluate_query_with_context(via_facade, cs, ctx) == expected


def test_evaluate_query_many_matches_per_row(sample_project: Path) -> None:
    """Batch facade output equals the per-row Python path on every spec."""
    specs = parser_facade.parse_project_file(str(sample_project))
    expr = raw_parse_query('"example"')
    expected = [raw_evaluator.evaluate_query(expr, cs, specs) for cs in specs]
    assert query_facade.evaluate_query_many('"example"', specs) == expected


@pytest.mark.parametrize(
    "query",
    [
        "ancestor:root",
        "ancestor:middle",
        "^root",
        "sibling:family",
        "sibling:family__260102_010101",
        "^root AND %w",
        "sibling:family OR ancestor:middle",
        "!ancestor:root",
    ],
)
def test_evaluate_query_many_matches_with_context_for_ancestor_and_sibling(
    ancestry_project: Path, query: str
) -> None:
    """Batch results match the per-row context path for ancestor/sibling filters."""
    specs = parser_facade.parse_project_file(str(ancestry_project))
    expr = raw_parse_query(query)
    ctx = raw_evaluator.build_query_context(specs)
    expected = [
        raw_evaluator.evaluate_query_with_context(expr, cs, ctx) for cs in specs
    ]
    assert query_facade.evaluate_query_many(query, specs) == expected


def test_unported_query_facade_apis_call_python_directly(
    sample_project: Path,
) -> None:
    """build_query_context / evaluate_query[_with_context] are intentionally
    Python-owned host logic. They must call the ``*_python`` helpers
    directly with no dispatcher in the call path.
    """
    specs = parser_facade.parse_project_file(str(sample_project))
    expr = raw_parse_query('"example"')
    ctx = query_facade.build_query_context(specs)
    direct_ctx = raw_evaluator.build_query_context(specs)

    assert set(ctx.name_map) == set(direct_ctx.name_map)
    assert query_facade.evaluate_query(expr, specs[0], specs) is True
    assert query_facade.evaluate_query_with_context(expr, specs[0], ctx) is True


def test_evaluate_query_many_runs_python_after_phase8b_deferral(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 8B reclassified ``evaluate_query_many`` as deferred/unported.

    The facade must execute the Python batch implementation directly. With
    a fake Rust module exposing ``evaluate_query_many`` the binding is
    *not* called — the facade no longer registers any Rust path for this
    surface.
    """
    specs = parser_facade.parse_project_file(str(sample_project))
    rust_calls: list[tuple[str, int]] = []

    def fake_evaluate(query: str, spec_dicts: list[dict]) -> list[bool]:
        rust_calls.append((query, len(spec_dicts)))
        return [False] * len(spec_dicts)

    install_fake_query_module(monkeypatch, evaluate_query_many=fake_evaluate)

    expected = query_facade._evaluate_query_many_python('"example"', specs)
    result = query_facade.evaluate_query_many('"example"', specs)
    assert result == expected
    assert rust_calls == []


def test_parse_query_uses_rust_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The facade calls the registered ``sase_core_rs.parse_query`` binding."""
    calls: list[str] = []

    def fake_parse_query(query: str) -> dict:
        calls.append(query)
        # Mirror the Python wire shape sase_core_rs emits for a single string.
        return {
            "kind": "string",
            "value": "x",
            "case_sensitive": False,
            "is_error_suffix": False,
            "is_running_agent": False,
            "is_running_process": False,
            "property_key": None,
            "operands": [],
        }

    install_fake_query_module(monkeypatch, parse_query=fake_parse_query)

    expr = query_facade.parse_query('"x"')
    assert calls == ['"x"']
    # The dict is rehydrated into the Python AST via the wire converters,
    # so the caller sees the same shape as the Python path.
    assert type(expr) is type(raw_parse_query('"x"'))


def test_parse_query_missing_extension_raises_importerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the wheel is gone, the facade raises :class:`ImportError`."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        query_facade.parse_query('"x"')


def test_parse_query_stale_wheel_raises_attributeerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel without the binding raises :class:`AttributeError` naming the op."""
    install_fake_query_module(monkeypatch)
    with pytest.raises(AttributeError, match="parse_query"):
        query_facade.parse_query('"x"')
