"""Tests for QueryEvaluationContext + evaluate_query_with_context."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.changespec import ChangeSpec
from sase.ace.query import build_query_context, evaluate_query_with_context
from sase.ace.query import context as context_mod
from sase.ace.query.parser import parse_query


def _cs(
    name: str,
    *,
    description: str = "desc",
    status: str = "Ready",
    parent: str | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path="/home/u/.sase/projects/demo/demo.gp",
        line_number=1,
    )


def _make_chain(n: int) -> list[ChangeSpec]:
    """root <- root_1 <- root_2 ... <- root_{n-1}."""
    specs = [_cs("root")]
    for i in range(1, n):
        specs.append(_cs(f"root_{i}", parent=specs[-1].name))
    return specs


def test_context_status_and_name_maps_built_eagerly() -> None:
    specs = [_cs("alpha", status="Draft"), _cs("beta", status="Mailed")]
    ctx = build_query_context(specs)
    assert ctx.name_map["alpha"].name == "alpha"
    assert ctx.name_map["beta"].name == "beta"
    assert ctx.status_map["alpha"] == "Draft"
    assert ctx.status_map["beta"] == "Mailed"


def test_context_caches_searchable_text_per_changespec() -> None:
    specs = [_cs("alpha"), _cs("beta")]
    ctx = build_query_context(specs)
    q = parse_query("alpha")

    real = context_mod.get_searchable_text
    with patch.object(context_mod, "get_searchable_text", side_effect=real) as spy:
        # Evaluate the same query 5 times against alpha and beta.
        for _ in range(5):
            evaluate_query_with_context(q, specs[0], ctx)
            evaluate_query_with_context(q, specs[1], ctx)
    # get_searchable_text should be called at most once per changespec.
    assert spy.call_count == 2


def test_ancestor_evaluation_does_not_rebuild_name_map_per_row() -> None:
    chain = _make_chain(50)
    ctx = build_query_context(chain)
    q = parse_query("ancestor:root")

    # Whatever happens internally, name_map should remain the one built up
    # front and ancestor_memo should accumulate (proof we reused state).
    pre_id = id(ctx.name_map)
    for cs in chain:
        assert evaluate_query_with_context(q, cs, ctx) is True
    assert id(ctx.name_map) == pre_id
    # Memoized at least one entry per spec walked.
    assert len(ctx.ancestor_memo) >= len(chain)


def test_evaluate_query_with_context_matches_reference_for_string_match() -> None:
    specs = [_cs("alpha"), _cs("beta")]
    ctx = build_query_context(specs)
    q = parse_query("alpha")
    assert evaluate_query_with_context(q, specs[0], ctx) is True
    assert evaluate_query_with_context(q, specs[1], ctx) is False


def test_evaluate_query_with_context_status_property() -> None:
    specs = [_cs("alpha", status="Draft"), _cs("beta", status="Ready")]
    ctx = build_query_context(specs)
    q = parse_query("status:Draft")
    assert evaluate_query_with_context(q, specs[0], ctx) is True
    assert evaluate_query_with_context(q, specs[1], ctx) is False
