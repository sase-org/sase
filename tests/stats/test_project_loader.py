"""The shared loader's availability, locking, and immutable presentation boundary."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from sase.project_display_names import ProjectDisplaySnapshot, ProjectRefDisplaySnapshot
from sase.stats.project import ProjectStatsQuery, ProjectStatsUnavailableError
from sase.stats.project import loader
from sase.stats.project.request import _ProjectStatsRequest
from sase.stats.project.view import build_project_stats_view
from sase.stats.ranges import StatsRange


@pytest.fixture
def wire():
    models = [
        {
            "kind": "resolved",
            "provider": "openai",
            "model": "gpt",
            "commits": 2,
            "plans": 1,
        },
        {
            "kind": "resolved",
            "provider": "openai",
            "model": "other",
            "commits": 3,
            "plans": 2,
        },
        {"kind": "unknown", "commits": 1, "unknown_reasons": ["page_unpublished"]},
        {"kind": "no_agent", "commits": 1},
    ]
    coverage = {
        "configured_repos": 2,
        "measured_repos": 1,
        "unavailable_repos": 1,
        "unknown_reasons": [{"reason": "page_unpublished", "count": 1}],
    }
    output = {
        "commits": 7,
        "agent_commits": 6,
        "plans_committed": 3,
        "models": models,
        "commit_coverage": coverage,
    }
    code = {
        "code_lines": 20,
        "test_lines": 5,
        "repos_configured": 2,
        "repos_measured": 1,
        "languages": [{"name": "Python", "files": 2, "lines": 20}],
    }
    runs = {"runs": 4, "completed": 3, "failed": 1, "total_runtime_seconds": 123.5}
    project = {
        "key": "alpha",
        "label": "Old Name",
        "state": "enabled",
        "output": output,
        "lifetime": {"commits": 200},
        "code": code,
        "runs": runs,
        "repos": [
            {
                "id": "primary:alpha",
                "name": "alpha",
                "kind": "primary",
                "tier": "code",
                "status": "ok",
                "ref": {"name": "HEAD", "commit": "a" * 40},
                "output": output,
                "snapshot": {
                    "tracked_files": 2,
                    "role_counts": [{"role": "tests", "files": 1, "lines": 5}],
                    "exclusion_counts": [
                        {
                            "exclusion": "generated",
                            "files": 1,
                            "reasons": [{"reason": "oversize", "files": 1}],
                        }
                    ],
                },
            }
        ],
        "models": models,
        "patches": [{"name": "fix", "status": "Merged", "runs": 4, "run_commits": 2}],
        "not_counted": [{"name": "personal", "reason": "user_linked"}],
        "coverage": coverage,
    }
    return {
        "schema_version": 1,
        "metric_policy_version": 1,
        "classifier_version": 1,
        "engine_version": 1,
        "range": {"start_ts": 0, "end_ts": 200},
        "fingerprint": "stable",
        "projects": [
            project,
            {
                "key": "lost",
                "label": "Unregistered",
                "state": "unregistered",
                "output": None,
                "code": None,
                "lifetime": None,
                "runs": runs,
                "repos": [],
            },
        ],
        "portfolio": {
            "output": output,
            "lifetime": {"commits": 200},
            "code": code,
            "runs": runs,
            "models": models,
            "coverage": coverage,
        },
        "issues": [
            {
                "project": "alpha",
                "repo": "missing",
                "code": "repo_unavailable",
                "message": "Missing repo",
            }
        ],
        "future_additive_field": {"kept": True},
    }


def _query():
    return ProjectStatsQuery(
        range=StatsRange(0, 200, "range", "Range"), project_refs=("alpha",)
    )


def _view(wire, **kwargs):
    return build_project_stats_view(
        wire,
        _query(),
        machine="apollo",
        generated_at="2026-10-17T00:00:00+00:00",
        timezone="UTC",
        facets={"output", "runs"},
        display_snapshot=ProjectDisplaySnapshot({"alpha": "Alpha Project"}),
        **kwargs,
    )


def test_view_decodes_full_wire_and_keeps_null_facets_and_raw_payload(wire):
    view = _view(wire)
    assert view.data == wire
    assert view.projects[0].label == "Alpha Project"
    assert view.projects[1].label == "Unregistered"
    assert view.projects[1].code is None
    assert view.projects[0].output.commits == 7
    assert view.projects[0].code.languages[0].name == "Python"
    assert view.repos[0].snapshot.role_counts[0].lines == 5
    assert view.repos[0].snapshot.exclusion_counts[0].reasons[0].reason == "oversize"
    assert view.patches[0].run_commits == 2
    assert view.coverage.unknown_reasons[0].count == 1
    assert view.code_pending
    assert view.effective_group_by == "project"
    assert replace(view, projects=view.projects[:1]).effective_group_by == "model"
    assert (
        replace(view, query=replace(view.query, group_by="repo")).effective_group_by
        == "repo"
    )
    with pytest.raises(FrozenInstanceError):
        view.projects[0].output.commits = 99
    wire["projects"][0]["output"]["commits"] = 500
    assert view.data["projects"][0]["output"]["commits"] == 7
    assert view.projects[0].output.commits == 7


def test_provider_subtotals_keep_unknown_and_no_agent_separate(wire):
    view = _view(wire)
    assert [
        (row.kind, row.provider, row.commits, row.plans)
        for row in view.provider_subtotals
    ] == [
        ("resolved", "openai", 5, 3),
        ("no_agent", None, 1, None),
        ("unknown", None, 1, None),
    ]


@pytest.fixture
def harness(monkeypatch, wire):
    state = {"locked": False, "observed": None, "include_run_only_projects": False}

    @contextmanager
    def lock():
        state["locked"] = True
        try:
            yield
        finally:
            state["locked"] = False

    def build(*args, **kwargs):
        return _ProjectStatsRequest(
            data={
                "timezone": "UTC",
                "include_run_only_projects": state["include_run_only_projects"],
                "projects": [],
            },
            refs=ProjectRefDisplaySnapshot(),
            issues=(),
        )

    def binding(request):
        state["observed"] = state["locked"]
        return wire

    monkeypatch.setattr(loader, "build_project_stats_request", build)
    monkeypatch.setattr(loader, "query_project_stats", binding)
    monkeypatch.setattr(loader, "agent_artifact_index_operation_lock", lock)
    return state


@pytest.mark.parametrize(
    "facets,run_only,expected",
    [
        ({"output", "runs"}, False, True),
        ({"output"}, False, False),
        ({"code"}, True, True),
    ],
)
def test_loader_locks_run_reads_and_uses_injected_clock(
    wire, harness, facets, run_only, expected
):
    harness["include_run_only_projects"] = run_only
    view = loader.load_project_stats(
        _query(),
        facets=facets,
        now=datetime(2026, 10, 17, tzinfo=UTC),
        machine="test-host",
    )
    assert harness["observed"] is expected
    assert not harness["locked"]
    assert view.machine == "test-host"
    assert view.generated_at == "2026-10-17T00:00:00+00:00"
    assert view.data == wire


@pytest.mark.parametrize("error", [ImportError, AttributeError])
def test_missing_binding_is_unavailable(harness, monkeypatch, error):
    def fail(request):
        raise error("project_stats_query missing")

    monkeypatch.setattr(loader, "query_project_stats", fail)
    with pytest.raises(
        ProjectStatsUnavailableError, match="project_stats_query missing"
    ):
        loader.load_project_stats(_query())
    assert not harness["locked"]


def test_all_sources_failed_is_error_but_empty_and_partial_are_success(wire, harness):
    wire["portfolio"] = {"output": {"commits": None, "plans_committed": None}}
    wire["projects"] = []
    with pytest.raises(ProjectStatsUnavailableError, match="Missing repo"):
        loader.load_project_stats(_query(), facets={"output"}, machine="host")
    wire["portfolio"]["output"]["commits"] = 0
    assert (
        loader.load_project_stats(
            _query(), facets={"output"}, machine="host"
        ).portfolio.output.commits
        == 0
    )
    wire["portfolio"]["output"]["commits"] = None
    wire["portfolio"]["output"]["plans_committed"] = 1
    assert (
        loader.load_project_stats(
            _query(), facets={"output"}, machine="host"
        ).portfolio.output.plans_committed
        == 1
    )
    wire["issues"] = []
    assert (
        loader.load_project_stats(_query(), facets={"output"}, machine="host").projects
        == ()
    )
