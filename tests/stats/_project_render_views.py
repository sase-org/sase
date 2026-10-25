"""Portfolio and view builders for project render fixtures."""

from __future__ import annotations

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.project.query import ProjectStatsQuery
from sase.stats.project.view import ProjectStatsView, build_project_stats_view
from tests.stats._project_render_base import (
    MACHINE,
    NOW_TS,
    RANGE,
    code,
    coverage,
    models,
    output,
    repo,
    runs,
)
from tests.stats._project_render_projects import bob_project, sase_project


def portfolio(projects: list[dict]) -> dict:
    commits = sum(
        (project.get("output") or {}).get("commits") or 0 for project in projects
    )
    plans = 0
    for project in projects:
        value = (project.get("output") or {}).get("plans_committed")
        if value:
            plans += value
    project_models = []
    for project in projects:
        project_models.extend(project.get("models") or [])
    collapsed: dict[tuple, dict] = {}
    for row in project_models:
        key = (row["kind"], row.get("provider"), row.get("model"))
        current = collapsed.setdefault(
            key,
            {
                **row,
                "commits": 0,
                "plans": 0,
                "plans_epic": 0,
                "plans_tale": 0,
            },
        )
        current["commits"] += row.get("commits") or 0
        current["plans"] += row.get("plans") or 0
        current["plans_epic"] += row.get("plans_epic") or 0
        current["plans_tale"] += row.get("plans_tale") or 0
    code_lines = sum(
        (project.get("code") or {}).get("code_lines") or 0 for project in projects
    )
    test_lines = sum(
        (project.get("code") or {}).get("test_lines") or 0 for project in projects
    )
    code_files = sum(
        (project.get("code") or {}).get("code_files") or 0 for project in projects
    )
    merged_languages: dict[str, dict] = {}
    for project in projects:
        for row in (project.get("code") or {}).get("languages") or []:
            current = merged_languages.setdefault(
                row["name"], {"name": row["name"], "files": 0, "lines": 0}
            )
            current["lines"] += row["lines"]
            current["files"] += row["files"]
    # Deduplicate repos shared by several projects: totals count each once.
    seen: dict[str, int] = {}
    for project in projects:
        for repo_row in project.get("repos") or []:
            if repo_row.get("tier") != "code":
                continue
            snapshot = repo_row.get("snapshot")
            if snapshot is None:
                continue
            repo_id = repo_row.get("id")
            seen[repo_id] = seen.get(repo_id, 0) + 1
    shared_ids = {repo_id for repo_id, count in seen.items() if count > 1}
    shared_lines = 0
    shared_files = 0
    shared_languages: dict[str, dict] = {}
    if len(projects) > 1 and shared_ids:
        for project in projects:
            for repo_row in project.get("repos") or []:
                if repo_row.get("id") not in shared_ids:
                    continue
                snapshot = repo_row.get("snapshot")
                if snapshot is None:
                    continue
                # Count each shared repo once: subtract every duplicate occurrence
                # after the first.
                key = repo_row.get("id")
                # Track occurrences across projects; first occurrence stays.
                shared_ids_seen = shared_languages.setdefault(
                    "_seen",
                    {},  # type: ignore[dict-item]
                )
                if key in shared_ids_seen:
                    for lang in snapshot.get("languages") or []:
                        if lang["name"] in merged_languages:
                            merged_languages[lang["name"]]["lines"] -= lang["lines"]
                            merged_languages[lang["name"]]["files"] -= lang["files"]
                    role_counts = snapshot.get("role_counts") or []
                    repo_total = sum(
                        row["lines"]
                        for row in role_counts
                        if row["role"] in ("source", "tests")
                    )
                    repo_files = sum(
                        row["files"]
                        for row in role_counts
                        if row["role"] in ("source", "tests")
                    )
                    code_lines -= repo_total
                    code_files -= repo_files
                    shared_lines += repo_total
                    shared_files += repo_files
                shared_ids_seen[key] = True
        # Drop the bookkeeping entry.
        shared_languages.pop("_seen", None)
        merged_languages = {
            name: row
            for name, row in merged_languages.items()
            if not name.startswith("_")
        }
    run_count = sum(
        (project.get("runs") or {}).get("runs") or 0 for project in projects
    )
    completed = sum(
        (project.get("runs") or {}).get("completed") or 0 for project in projects
    )
    seconds = sum(
        (project.get("runs") or {}).get("total_runtime_seconds") or 0
        for project in projects
    )
    portfolio_languages = sorted(
        merged_languages.values(),
        key=lambda row: (-row["lines"], -row["files"], row["name"]),
    )
    if len(projects) > 1:
        configured = 10
        measured = 9
    else:
        configured = (projects[0].get("code") or {}).get("repos_configured", 0)
        measured = (projects[0].get("code") or {}).get("repos_measured", 0)
    return {
        "output": output(commits, plans, list(collapsed.values())),
        "lifetime": {"commits": 18655, "age_days": 245, "last_commit_ts": NOW_TS - 240},
        "code": code(
            lines=code_lines,
            tests=test_lines,
            docs=90_000,
            configured=configured,
            measured=measured,
            languages=portfolio_languages,
            files=code_files,
        ),
        "runs": runs(
            runs=run_count,
            completed=completed,
            failed=run_count - completed,
            seconds=seconds,
            patches=27,
        ),
        "models": list(collapsed.values()),
        "coverage": (
            projects[0].get("coverage") or coverage()
            if len(projects) == 1
            else coverage()
        ),
    }


def build_view(
    *,
    projects: list[dict] | None = None,
    facets: set[str] | None = None,
    group_by: str | None = None,
    project_refs: tuple[str, ...] = (),
) -> ProjectStatsView:
    rows = projects if projects is not None else [sase_project(), bob_project()]
    wire = {
        "schema_version": 1,
        "metric_policy_version": 1,
        "classifier_version": 1,
        "engine_version": 1,
        "range": {"start_ts": RANGE.start_ts, "end_ts": RANGE.end_ts},
        "fingerprint": "golden",
        "projects": rows,
        "portfolio": portfolio(rows),
        "issues": [
            {
                "project": "gh_sase-org__sase",
                "repo": "missing",
                "code": "not_cloned",
                "message": "not cloned",
            }
        ],
    }
    query = ProjectStatsQuery(
        range=RANGE,
        project_refs=project_refs,
        preset="7d",
        group_by=group_by,  # type: ignore[arg-type]
    )
    labels = {row["key"]: row["label"] for row in rows}
    return build_project_stats_view(
        wire,
        query,
        machine=MACHINE,
        generated_at="2026-10-16T18:00:00-04:00",
        timezone="America/New_York",
        facets=facets or {"output", "code", "runs"},
        display_snapshot=ProjectDisplaySnapshot(labels),
    )


def one_project_view(**kwargs: object) -> ProjectStatsView:
    return build_view(projects=[sase_project()], project_refs=("sase",), **kwargs)


def repo_edge_view() -> ProjectStatsView:
    """Cover partial, shared, overflow, quiet, and unknown-status repo rows."""
    project = sase_project()
    project["label"] = "widgets"
    project["repos"] = [
        repo(name="widgets", kind="primary", tier="code", commits=380),
        repo(
            name="widgets-core",
            kind="linked",
            tier="code",
            status="partial",
            commits=32,
        ),
        repo(name="widgets-cli", kind="linked", tier="code", commits=20),
        repo(name="widgets-ui", kind="linked", tier="code", commits=15),
        repo(name="widgets-docs", kind="linked", tier="code", commits=10),
        repo(name="widgets-tools", kind="linked", tier="code", commits=8),
        repo(name="widgets-infra", kind="linked", tier="code", commits=7),
        repo(name="widgets-extra", kind="linked", tier="code", commits=5),
        repo(name="widgets-tiny", kind="linked", tier="code", commits=1),
        repo(name="widgets-nvim", kind="linked", tier="code", commits=0),
        repo(
            name="widgets-future",
            kind="linked",
            tier="code",
            status="future_status",
            commits=4,
        ),
        repo(
            name="widgets-missing",
            kind="linked",
            tier="code",
            status="unavailable",
            issue={"code": "not_cloned", "message": "not cloned"},
        ),
    ]
    project["code"] = code(
        lines=100_000, tests=35_000, docs=5_000, configured=12, measured=11
    )
    return build_view(projects=[project], project_refs=("widgets",))


def all_projects_view(**kwargs: object) -> ProjectStatsView:
    return build_view(**kwargs)


def empty_range_view() -> ProjectStatsView:
    empty_output = output(0, 0, [])
    empty_output["plans_committed"] = 0
    project = sase_project(
        output=empty_output,
        models=[],
        runs=runs(runs=0, completed=0, failed=0, seconds=0, patches=0),
        patches=[],
        coverage={
            "configured_repos": 7,
            "measured_repos": 6,
            "unavailable_repos": 1,
            "agent_tagged_commits": 0,
            "resolved_agent_commits": 0,
            "unknown_agent_commits": 0,
            "unknown_reasons": [],
        },
    )
    for repo_row in project["repos"]:
        repo_output = repo_row.get("output")
        if repo_output is not None:
            repo_output.update({"commits": 0, "agent_commits": 0, "agent_share": 0.0})
    return build_view(projects=[project], project_refs=("sase",))


def local_plans_view() -> ProjectStatsView:
    project_output = output(412, 0, models())
    project_output["plans_committed"] = None
    project_output["plans_epic"] = None
    project_output["plans_tale"] = None
    return build_view(
        projects=[sase_project(output=project_output)], project_refs=("sase",)
    )


def code_pending_view() -> ProjectStatsView:
    project = sase_project(code=None)
    return build_view(
        projects=[project],
        project_refs=("sase",),
        facets={"output", "runs"},
    )
