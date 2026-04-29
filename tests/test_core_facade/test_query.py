"""Tests for ``sase.core.query_facade``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.ace.query import evaluator as raw_evaluator
from sase.ace.query.parser import parse_query_python as raw_parse_query
from sase.core import parser_facade, query_facade
from sase.core.backend import (
    BACKEND_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    RustBackendUnavailableError,
)

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


def test_unported_query_facade_apis_rust_without_impl_fall_back_to_python(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    specs = parser_facade.parse_project_file(str(sample_project))
    expr = raw_parse_query('"example"')
    ctx = query_facade.build_query_context(specs)
    direct_ctx = raw_evaluator.build_query_context(specs)

    assert set(ctx.name_map) == set(direct_ctx.name_map)
    assert query_facade.evaluate_query(expr, specs[0], specs) is True
    assert query_facade.evaluate_query_with_context(expr, specs[0], ctx) is True


def test_evaluate_query_many_under_rust_runs_python_after_phase8b_deferral(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 8B reclassified ``evaluate_query_many`` as deferred/unported.

    Even with ``SASE_CORE_BACKEND=rust`` the facade must execute the Python
    batch implementation. We assert that with a fake Rust module exposing
    ``evaluate_query_many`` the binding is *not* called — the facade no
    longer registers a ``rust_impl`` for this surface.
    """
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
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


def test_parse_query_rust_without_impl_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parse_query routes to the Rust binding only when the extension is
    importable; without it, ``SASE_CORE_BACKEND=rust`` must still raise.
    """
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError):
        query_facade.parse_query('"x"')


def test_parse_query_rust_backend_uses_rust_impl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SASE_CORE_BACKEND=rust`` routes parse_query through the binding."""
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
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    expr = query_facade.parse_query('"x"')
    assert calls == ['"x"']
    # The dict is rehydrated into the Python AST via the wire converters,
    # so the caller sees the same shape as the Python path.
    assert type(expr) is type(raw_parse_query('"x"'))


def test_parse_query_rust_backend_missing_binding_raises_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_query_module(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    with pytest.raises(RustBackendUnavailableError, match="parse_query"):
        query_facade.parse_query('"x"')


def test_evaluate_query_many_dual_run_is_noop_after_phase8b_deferral(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run produces no record for the deferred ``evaluate_query_many``.

    Phase 8B removed the Rust adapter from the facade. With no ``rust_impl``
    registered, ``SASE_CORE_DUAL_RUN=1`` must be a no-op for this surface
    even when ``sase_core_rs`` exposes a binding — the facade no longer
    consults the extension.
    """
    from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR

    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv("SASE_CORE_DUAL_RUN", "1")
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

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
    assert not log_path.exists() or log_path.read_text() == ""
