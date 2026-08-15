"""Document vocabulary coverage for Plans filtering."""

from __future__ import annotations

from pathlib import Path

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_filtering import (
    build_plan_filter_index,
)
from sase.ace.tui.widgets.artifacts.query_rows import build_plans_query_index
from sase.core.query_profile_corpus_facade import evaluate_artifact_query_many
from tests.ace.tui._artifacts_plans_helpers import _snapshot


def _matched_kinds(tmp_path: Path, query: str) -> list[str]:
    profile = compiled_profile_for_builtin_pane("ref:plan")
    assert profile is not None
    filter_index, query_index = build_plans_query_index(
        _snapshot(tmp_path),
        pane_id="ref:plan",
        generation=1,
        profile=profile,
    )
    matched_ids = frozenset(
        evaluate_artifact_query_many(query, query_index).matched_row_ids
    )
    return [record.kind for record in filter_index if record.option_id in matched_ids]


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
