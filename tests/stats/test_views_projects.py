import pytest

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.views import build_statistics_views
from tests._project_display_case import ProjectDisplayCase
from tests.stats._views_payloads import activity_payload, run_payload


@pytest.mark.parametrize("group_by", ["project", "patch"])
def test_runtime_work_group_literals_round_trip(group_by: str) -> None:
    payload = run_payload()
    payload["runtime_group_by"] = group_by

    views = build_statistics_views(payload, activity_payload())

    assert views.runtime.group_by == group_by


def test_work_rows_tolerate_partial_and_invalid_values() -> None:
    views = build_statistics_views(
        {
            "work": {
                "projects": [{"project": "sase", "runs": True}],
                "changespecs": [  # legacy wire key
                    {
                        "project": "sase",
                        "name": "orphan",
                        "status": "",
                        "has_pr": "yes",
                    }
                ],
                "truncated_patch_rows": 2,
            }
        },
        {},
    )

    assert views.projects.project_count == 1
    assert views.projects.patch_count == 3
    assert views.projects.projects[0].runs == 0
    assert views.projects.projects[0].patches[0].status == "unknown"
    assert views.projects.projects[0].patches[0].has_pr is False


def test_project_display_snapshot_projects_every_project_bearing_row(
    project_display_case: ProjectDisplayCase,
) -> None:
    payload = run_payload()
    widgets_key = project_display_case.project_key
    payload["workspaces"][0]["project"] = widgets_key  # type: ignore[index]
    payload["work"]["projects"][0]["project"] = widgets_key  # type: ignore[index]
    payload["work"]["changespecs"][0].update(  # type: ignore[index,union-attr]  # legacy wire key
        {
            "project": widgets_key,
            "name": project_display_case.patch_key,
        }
    )
    payload["runtime_group_by"] = "project"
    payload["runtime_groups"][0]["group"] = widgets_key  # type: ignore[index]
    snapshot = project_display_case.snapshot

    views = build_statistics_views(
        payload,
        activity_payload(),
        project_display_snapshot=snapshot,
    )

    project = views.projects.projects[0]
    assert (project.project_key, project.project_label) == (
        widgets_key,
        project_display_case.project_label,
    )
    assert [row.patch_key for row in project.patches] == [
        project_display_case.patch_key
    ]
    assert project.patches[0].patch_label == project_display_case.patch_label
    assert (
        project.patches[0].project_key,
        project.patches[0].project_label,
    ) == (widgets_key, project_display_case.project_label)
    assert (
        views.activity.workspaces[0].project_key,
        views.activity.workspaces[0].project_label,
    ) == (widgets_key, project_display_case.project_label)
    assert (
        views.runtime.rows[0].group_key,
        views.runtime.rows[0].group_label,
    ) == (widgets_key, project_display_case.project_label)
    assert views.projects.projects[1].project_label == "core"


def test_patch_runtime_groups_are_humanized_without_losing_identity(
    project_display_case: ProjectDisplayCase,
) -> None:
    payload = run_payload()
    patch_key, patch_label = project_display_case.patch("repair_labels")
    payload["runtime_group_by"] = "patch"
    payload["runtime_groups"][0]["group"] = patch_key  # type: ignore[index]

    runtime = build_statistics_views(
        payload,
        activity_payload(),
        project_display_snapshot=project_display_case.snapshot,
    ).runtime

    assert (runtime.rows[0].group_key, runtime.rows[0].group_label) == (
        patch_key,
        patch_label,
    )


def test_ranked_project_ties_sort_by_visible_label_then_canonical_key() -> None:
    payload = run_payload()
    projects = payload["work"]["projects"]  # type: ignore[index]
    for row, project_key in zip(  # type: ignore[assignment]
        projects,
        ("gh_zed__widgets", "gh_acme__widgets"),
        strict=True,
    ):
        row["project"] = project_key
        row["runs"] = 4
    payload["work"]["changespecs"] = []  # type: ignore[index]  # legacy wire key
    snapshot = ProjectDisplaySnapshot(
        {
            "gh_zed__widgets": "widgets",
            "gh_acme__widgets": "widgets",
        }
    )

    rows = build_statistics_views(
        payload,
        activity_payload(),
        project_display_snapshot=snapshot,
    ).projects.projects

    assert [(row.project_label, row.project_key) for row in rows] == [
        ("widgets", "gh_acme__widgets"),
        ("widgets", "gh_zed__widgets"),
    ]
