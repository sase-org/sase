"""Tests for ``sase.core.query_facade``.

:func:`sase.core.query_facade.parse_query` calls ``sase_core_rs`` directly
through :func:`sase.core.rust.require_rust_binding`. The unported entry
points (per-row evaluators, ``build_query_context``, the deferred
``evaluate_query_many`` batch path) call their Python implementations
directly as host logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.ace.query import evaluator as raw_evaluator
from sase.ace.query.parser import parse_query_python as raw_parse_query
from sase.core import parser_facade, query_corpus_facade, query_facade
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.wire_conversion import changespec_to_wire

from tests.test_core_facade._helpers import install_fake_query_module


class _FakeRustCorpus:
    def __init__(self, length: int) -> None:
        self.length = length

    def __len__(self) -> int:
        return self.length


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


def test_compile_query_corpus_converts_specs_once(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corpus compilation converts each ChangeSpec once before crossing FFI."""
    specs = parser_facade.parse_project_file(str(sample_project))
    converted_names: list[str] = []
    compiled_batches: list[list[dict]] = []

    def tracking_changespec_to_wire(cs):
        converted_names.append(cs.name)
        return changespec_to_wire(cs)

    def fake_compile_corpus(spec_dicts: list[dict]) -> _FakeRustCorpus:
        compiled_batches.append(spec_dicts)
        return _FakeRustCorpus(len(spec_dicts))

    install_fake_query_module(monkeypatch, compile_corpus=fake_compile_corpus)
    monkeypatch.setattr(
        query_corpus_facade, "changespec_to_wire", tracking_changespec_to_wire
    )

    corpus = query_corpus_facade.compile_query_corpus(specs)

    assert converted_names == [cs.name for cs in specs]
    assert len(compiled_batches) == 1
    assert [record["name"] for record in compiled_batches[0]] == [
        cs.name for cs in specs
    ]
    assert corpus.source_list_id == id(specs)
    assert corpus.expected_length == len(specs)


def test_evaluate_query_many_with_corpus_uses_handle_api_not_legacy(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent corpus evaluation must not call legacy evaluate_query_many."""
    specs = parser_facade.parse_project_file(str(sample_project))
    calls: list[tuple[str, object]] = []
    rust_corpus = _FakeRustCorpus(len(specs))

    def fake_compile_query(query: str) -> object:
        calls.append(("compile_query", query))
        return {"query": query}

    def fake_evaluate_many(program: object, corpus: object) -> list[bool]:
        calls.append(("evaluate_many", program))
        assert corpus is rust_corpus
        return [True, False]

    def fake_legacy_evaluate_many(query: str, spec_dicts: list[dict]) -> list[bool]:
        raise AssertionError("legacy evaluate_query_many should not be called")

    install_fake_query_module(
        monkeypatch,
        compile_query=fake_compile_query,
        evaluate_many=fake_evaluate_many,
        evaluate_query_many=fake_legacy_evaluate_many,
    )
    corpus = query_corpus_facade.QueryCorpus(
        source_list_id=id(specs),
        expected_length=len(specs),
        rust_handle=rust_corpus,
    )

    assert query_corpus_facade.evaluate_query_many_with_corpus('"example"', corpus) == [
        True,
        False,
    ]
    assert calls == [
        ("compile_query", '"example"'),
        ("evaluate_many", {"query": '"example"'}),
    ]


def test_evaluate_query_many_with_stale_corpus_refuses_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Length mismatches fail before query compilation or evaluation."""
    calls: list[str] = []

    def fake_compile_query(query: str) -> object:
        calls.append("compile_query")
        return object()

    def fake_evaluate_many(program: object, corpus: object) -> list[bool]:
        calls.append("evaluate_many")
        return [False]

    install_fake_query_module(
        monkeypatch,
        compile_query=fake_compile_query,
        evaluate_many=fake_evaluate_many,
    )
    stale = query_corpus_facade.QueryCorpus(
        source_list_id=123,
        expected_length=2,
        rust_handle=_FakeRustCorpus(1),
    )

    with pytest.raises(ValueError, match="stale query corpus wrapper"):
        query_corpus_facade.evaluate_query_many_with_corpus('"example"', stale)
    assert calls == []


def test_compile_query_corpus_missing_binding_raises_attributeerror(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale wheels fail through require_rust_binding with the missing op name."""
    specs = parser_facade.parse_project_file(str(sample_project))
    install_fake_query_module(monkeypatch)

    with pytest.raises(AttributeError, match="compile_corpus"):
        query_corpus_facade.compile_query_corpus(specs)


def test_evaluate_query_many_with_corpus_missing_binding_raises_attributeerror(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evaluation surfaces stale wheels through the strict Rust binding loader."""
    specs = parser_facade.parse_project_file(str(sample_project))
    corpus = query_corpus_facade.QueryCorpus(
        source_list_id=id(specs),
        expected_length=len(specs),
        rust_handle=_FakeRustCorpus(len(specs)),
    )
    install_fake_query_module(monkeypatch, evaluate_many=lambda _p, _c: [])

    with pytest.raises(AttributeError, match="compile_query"):
        query_corpus_facade.evaluate_query_many_with_corpus('"example"', corpus)


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
