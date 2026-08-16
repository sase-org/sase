"""Coverage for declarative generic document-provider panes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui._artifact_tab_model import PanePresentation, PaneRowPresentation
from sase.ace.tui.widgets.artifacts.plans_data import _provider_archive_sort_key
from sase.ace.tui.widgets.artifacts.plans_data_models import ProjectArchive
from sase.ace.tui.widgets.artifacts.plans_list import build_plan_options
from sase.ace.tui.widgets.artifacts.query_rows import build_plans_query_index
from sase.core.query_profile_corpus_facade import evaluate_artifact_query_many
from sase.plan_search.model import Plan, PlanSearchMatch
from tests.ace.tui._artifacts_plans_helpers import _snapshot


def _contract():
    result = compile_provider_contract(
        kind="research",
        label="Research",
        icon="∴",
        accent="#058D1D",
        spec={
            "schema_version": 1,
            "provider": "research",
            "ref": {
                "kind": "research",
                "icon": "∴",
                "properties": {
                    "updated_time": {"type": "datetime"},
                    "status": {"type": "enum", "values": ["draft", "final"]},
                    "tags": {"type": "string_list"},
                },
                "inventory": {"globs": ["20*/**/*.md"]},
                "identity": {},
                "publication": {},
                "pane": {
                    "row": {
                        "title": "title",
                        "badges": ["status"],
                        "secondary": ["updated_time"],
                        "list_fields": ["tags"],
                    },
                    "default_sort": [{"field": "updated_time", "direction": "desc"}],
                    "facets": ["status", "tags"],
                    "group_by": "status",
                    "empty_state": {
                        "title": "No research",
                        "body": "No matching research.",
                    },
                },
            },
        },
        provider_spec_digest="wire",
    )
    assert result.error is None
    return result.contract


def _archive(
    tmp_path: Path,
    name: str,
    *,
    status: str,
    updated_time: str,
    tags: str,
) -> ProjectArchive:
    path = tmp_path / f"{name}.md"
    match = PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="research",
            path=str(path),
            relpath=f"202608/{name}.md",
            name=name,
            title=name.replace("_", " ").title(),
            status=status,
            created_at=updated_time,
            prompt_link="",
            summary="",
            body=f"{name} body.",
            frontmatter={
                "status": status,
                "updated_time": updated_time,
                "tags": tags,
            },
        ),
        matched_fields=[],
        score=1.0,
    )
    return ProjectArchive("alpha", match, "research")


def _research_snapshot(tmp_path: Path, archive: tuple[ProjectArchive, ...]):
    contract = _contract()
    return replace(
        _snapshot(tmp_path),
        proposals=(),
        active=(),
        archive=archive,
        provider_kind="research",
        provider_label="Research",
        provider_presentation_digest=contract.presentation_digest,
        provider_presentation=contract.presentation,
    )


def test_provider_rows_render_declared_fields_without_plan_sections(
    tmp_path: Path,
) -> None:
    snapshot = _research_snapshot(
        tmp_path,
        (
            _archive(
                tmp_path,
                "final_report",
                status="final",
                updated_time="2026-08-12 10:00:00",
                tags="agents, evals",
            ),
        ),
    )

    options, rows, _known_group_keys = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
    )

    assert len(rows) == 1
    prompts = [option.prompt.plain for option in options]
    assert any(
        "Final Report  final  2026-08-12 10:00:00  agents, evals" in item
        for item in prompts
    )
    assert all("No pending proposals" not in item for item in prompts)
    assert all("No active plans" not in item for item in prompts)


def test_provider_default_sort_is_stable_and_declared(
    tmp_path: Path,
) -> None:
    contract = _contract()
    older = _archive(
        tmp_path,
        "older",
        status="final",
        updated_time="2026-08-11 10:00:00",
        tags="agents",
    )
    newer = _archive(
        tmp_path,
        "newer",
        status="draft",
        updated_time="2026-08-12 10:00:00",
        tags="evals",
    )
    tie = _archive(
        tmp_path,
        "same_time",
        status="draft",
        updated_time="2026-08-12 10:00:00",
        tags="evals",
    )

    ordered = sorted(
        (older, tie, newer),
        key=lambda item: _provider_archive_sort_key(item, contract.presentation),
    )

    assert [entry.match.plan.name for entry in ordered] == [
        "newer",
        "same_time",
        "older",
    ]


def test_provider_query_facets_and_grouping_use_declared_fields(
    tmp_path: Path,
) -> None:
    contract = _contract()
    snapshot = _research_snapshot(
        tmp_path,
        (
            _archive(
                tmp_path,
                "draft_report",
                status="draft",
                updated_time="2026-08-12 10:00:00",
                tags="agents",
            ),
            _archive(
                tmp_path,
                "final_report",
                status="final",
                updated_time="2026-08-11 10:00:00",
                tags="evals",
            ),
        ),
    )
    filter_index, query_index = build_plans_query_index(
        snapshot,
        pane_id="ref:research",
        generation=1,
        profile=contract.query_profile,
    )
    result = evaluate_artifact_query_many("status:final", query_index)
    mode = contract.grouping.modes[0]

    _options, rows, known_group_keys = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
        mode=mode,
        matched_option_ids=frozenset(result.matched_row_ids),
    )

    assert query_index.facets["status"] == ("draft", "final")
    assert query_index.facets["tags"] == ("agents", "evals")
    assert [record.kind for record in filter_index] == ["archive", "archive"]
    assert tuple(rows) == result.matched_row_ids
    assert known_group_keys == (("final",),)


def test_provider_empty_option_uses_provider_label(tmp_path: Path) -> None:
    snapshot = replace(
        _research_snapshot(tmp_path, ()),
        provider_presentation=PanePresentation(
            row=PaneRowPresentation(title="title"),
        ),
    )

    options, rows, _known_group_keys = build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
    )

    assert rows == {}
    assert [option.prompt.plain for option in options] == ["  No research documents"]
