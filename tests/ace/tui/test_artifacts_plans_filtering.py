"""Document vocabulary coverage for Plans filtering."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_filtering import (
    build_plan_filter_index,
    compile_plan_matcher,
)
from sase.plan_search.filter_query import parse_plan_filter_query
from tests.ace.tui._artifacts_plans_helpers import _snapshot


def _matched_kinds(tmp_path: Path, query: str) -> list[str]:
    index = build_plan_filter_index(_snapshot(tmp_path))
    matcher = compile_plan_matcher(parse_plan_filter_query(query))
    return [record.kind for record in index if matcher(record)]


def test_filter_index_contains_only_document_section_kinds(tmp_path: Path) -> None:
    index = build_plan_filter_index(_snapshot(tmp_path))

    assert [record.kind for record in index] == ["proposal", "active", "archive"]
    assert _matched_kinds(tmp_path, "kind:active") == ["active"]
    assert _matched_kinds(tmp_path, "kind:plans") == ["active", "archive"]
    assert _matched_kinds(tmp_path, "status:proposed") == ["proposal"]
    assert _matched_kinds(tmp_path, "status:wip") == ["active"]
    assert _matched_kinds(tmp_path, "status:done") == ["archive"]


def test_plan_filter_bar_drops_bead_kind_and_status_completions() -> None:
    kinds = PlanFilterBar.STATIC_VALUE_COMPLETIONS["kind"]
    statuses = PlanFilterBar.STATIC_VALUE_COMPLETIONS["status"]

    assert kinds == ("proposal", "active", "archive", "plans", "research")
    assert statuses == ("proposed",)
    assert {"task", "epic", "phase"}.isdisjoint(kinds)
    assert {"open", "claimed", "ready", "blocked"}.isdisjoint(statuses)
