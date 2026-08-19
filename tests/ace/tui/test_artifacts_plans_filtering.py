"""Document vocabulary coverage for Plans filtering."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import Static

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.testing import AcePage
from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui.widgets.artifacts import plans_pane
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_data import DEEP_ARCHIVE_PER_PROJECT_LIMIT
from sase.ace.tui.widgets.artifacts.plans_deep_archive import DeepArchiveResult
from sase.ace.tui.widgets.artifacts.plans_filtering import (
    build_plan_filter_index,
)
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.ace.tui.widgets.artifacts.query_rows import build_plans_query_index
from sase.ace.tui.widgets.artifacts.types import ARTIFACTS_ACCENTS
from sase.core.query_profile_corpus_facade import evaluate_artifact_query_many
from sase.plan_search.filter_query import parse_plan_filter_query
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot


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


async def test_clicking_idle_plan_bar_opens_the_filter_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        bar = pane.query_one(PlanFilterBar)
        assert not pane._filter_session_open

        await page.click("#plan-filter-bar")
        await page.pause()

        assert pane._filter_session_open
        assert bar._editing  # type: ignore[attr-defined]


async def test_committing_plan_query_updates_idle_bar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        bar = pane.query_one(PlanFilterBar)
        display = bar.query_one("#plan-filter-display", Static)

        await page.press("/")
        bar.set_query("kind:active")
        bar.post_message(PlanFilterBar.Submitted("kind:active"))
        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]

        assert pane.filters.kinds == ("active",)
        assert display.render().plain == "kind:active"


async def test_changing_project_scope_keeps_idle_plan_bar_in_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = _snapshot(tmp_path)
    beta = replace(
        alpha,
        project="beta",
        projects=("beta",),
        display_names={"beta": "Beta"},
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda project, **_kwargs: alpha if project == "alpha" else beta,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        pane.set_project_scope("alpha")
        await page.wait_for(lambda _state: pane.snapshot is alpha)
        bar = pane.query_one(PlanFilterBar)
        display = bar.query_one("#plan-filter-display", Static)

        await page.press("/")
        bar.set_query("kind:active")
        bar.post_message(PlanFilterBar.Submitted("kind:active"))
        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]
        assert display.render().plain == "kind:active"

        pane.set_project_scope("beta")
        await page.wait_for(lambda _state: pane.snapshot is beta)

        assert display.render().plain == "kind:active"


async def test_plan_bar_geometry_is_unchanged_between_idle_and_editing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        option_list = pane.query_one("#plans-list")
        idle_region = option_list.region
        assert idle_region.height > 0

        await page.press("/")
        await page.pause()
        assert option_list.region == idle_region

        await page.press("escape")
        await page.pause()
        assert option_list.region == idle_region


async def test_deep_archive_coverage_label_is_visible_in_idle_status_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = replace(_snapshot(tmp_path), archive_truncated=True)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        plans_pane,
        "load_plans_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("ref:plan"))
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsDocumentsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)

        filters = parse_plan_filter_query("Active")
        request = pane._deep_archive_request_for(filters)  # type: ignore[attr-defined]
        assert request is not None
        pane._deep_archive_cache[request] = DeepArchiveResult(  # type: ignore[attr-defined]
            request=request,
            archive=(),
            filter_index=pane._filter_index,  # type: ignore[attr-defined]
            query_index=pane._query_index,
            query_result=None,
            scanned_count=DEEP_ARCHIVE_PER_PROJECT_LIMIT,
            capped=True,
            errors=(),
        )
        pane.filters = filters
        pane._refresh_options()  # type: ignore[attr-defined]
        await page.pause()

        bar = pane.query_one(PlanFilterBar)
        status = bar.query_one("#plan-filter-status", Static)
        assert not pane._filter_session_open
        assert (
            f"newest {DEEP_ARCHIVE_PER_PROJECT_LIMIT} searched" in status.render().plain
        )


async def test_document_provider_pane_bar_renders_in_its_own_accent() -> None:
    """A non-Plan document provider's persistent bar must not draw Plans-purple."""
    contract = compile_provider_contract(
        kind="research",
        label="Research",
        icon="R",
        accent="#058D1D",
        spec=None,
        provider_spec_digest="w",
    ).contract
    assert contract is not None

    class _ProviderPaneApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

        def compose(self) -> ComposeResult:
            yield ArtifactsDocumentsPane(contract=contract)

    app = _ProviderPaneApp()
    async with app.run_test():
        bar = app.query_one(PlanFilterBar)
        sigil = bar.query_one(f"#{bar.SIGIL_ID}", Static)
        expected = Color.parse(contract.accent)

        assert bar.ACCENT == contract.accent
        assert sigil.styles.color == expected
        for other in ARTIFACTS_ACCENTS.values():
            if other == contract.accent:
                continue
            assert sigil.styles.color != Color.parse(other)
