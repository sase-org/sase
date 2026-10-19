"""Pinned ProjectStatsView fixtures for renderer goldens."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.project.query import ProjectStatsQuery
from sase.stats.project.view import ProjectStatsView, build_project_stats_view
from sase.stats.ranges import StatsRange
from sase.stats.render.context import RenderContext

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 16, 18, 0, tzinfo=TZ)
NOW_TS = int(NOW.timestamp())
MACHINE = "apollo"
RANGE = StatsRange(
    NOW_TS - 7 * 86400,
    NOW_TS,
    "Oct 09 – Oct 16, 2026",
    "Last 7 days",
)


def render_context(
    *, width: int, unicode: bool = True, color: bool = False
) -> RenderContext:
    return RenderContext(
        width=width,
        color=color,
        unicode=unicode,
        now=NOW,
        timezone=TZ,
        machine=MACHINE,
    )


def _models() -> list[dict]:
    return [
        {
            "kind": "resolved",
            "provider": "codex",
            "model": "gpt-6-luna",
            "commits": 61,
            "plans": 9,
            "plans_epic": 2,
            "plans_tale": 7,
        },
        {
            "kind": "resolved",
            "provider": "codex",
            "model": "gpt-6.1-sol",
            "commits": 37,
            "plans": 9,
            "plans_epic": 3,
            "plans_tale": 6,
        },
        {
            "kind": "resolved",
            "provider": "claude",
            "model": "opus",
            "commits": 40,
            "plans": 30,
            "plans_epic": 8,
            "plans_tale": 22,
        },
        {
            "kind": "resolved",
            "provider": "claude",
            "model": "sonnet",
            "commits": 31,
            "plans": 1,
            "plans_epic": 0,
            "plans_tale": 1,
        },
        {
            "kind": "resolved",
            "provider": "muse",
            "model": "auto",
            "commits": 156,
            "plans": 4,
            "plans_epic": 1,
            "plans_tale": 3,
        },
        {
            "kind": "resolved",
            "provider": "grok",
            "model": "grok-4",
            "commits": 52,
            "plans": 6,
            "plans_epic": 0,
            "plans_tale": 6,
        },
        {
            "kind": "resolved",
            "provider": "openai",
            "model": "@default",
            "model_is_alias": True,
            "commits": 4,
            "plans": 0,
            "plans_epic": 0,
            "plans_tale": 0,
        },
        {
            "kind": "unknown",
            "commits": 27,
            "plans": 2,
            "plans_epic": 0,
            "plans_tale": 2,
            "unknown_reasons": ["page_unpublished"],
        },
        {
            "kind": "no_agent",
            "commits": 4,
            "plans": 0,
            "plans_epic": 0,
            "plans_tale": 0,
        },
    ]


def _coverage() -> dict:
    return {
        "configured_repos": 7,
        "measured_repos": 6,
        "unavailable_repos": 1,
        "agent_tagged_commits": 408,
        "resolved_agent_commits": 381,
        "unknown_agent_commits": 27,
        "unknown_reasons": [{"reason": "page_unpublished", "count": 27}],
    }


def _output(commits: int, plans: int, models: list[dict]) -> dict:
    agent = sum(row["commits"] for row in models if row["kind"] != "no_agent")
    return {
        "commits": commits,
        "agent_commits": agent,
        "agent_share": agent / commits if commits else 0.0,
        "plans_committed": plans,
        "plans_epic": sum(row.get("plans_epic") or 0 for row in models),
        "plans_tale": sum(row.get("plans_tale") or 0 for row in models),
        "models": models,
        "commit_coverage": _coverage(),
        "plan_coverage": _coverage(),
    }


def _code(*, lines: int, tests: int, docs: int, configured: int, measured: int) -> dict:
    return {
        "counter": "sloc",
        "code_lines": lines,
        "test_lines": tests,
        "test_share": tests / lines if lines else None,
        "doc_lines": docs,
        "repos_configured": configured,
        "repos_measured": measured,
        "languages": [{"name": "Python", "files": 12, "lines": lines}],
    }


def _runs(
    *, runs: int, completed: int, failed: int, seconds: float, patches: int
) -> dict:
    return {
        "runs": runs,
        "completed": completed,
        "failed": failed,
        "success_rate": completed / runs if runs else None,
        "total_runtime_seconds": seconds,
        "distinct_patches": patches,
        "unattributed_runs": 3,
        "last_run_ts": NOW_TS - 240,
    }


def _repo(
    *,
    name: str,
    kind: str,
    tier: str,
    status: str = "ok",
    commits: int = 0,
    issue: dict | None = None,
    files: int | None = 10,
    lines: int | None = 1000,
) -> dict:
    return {
        "id": f"{kind}:{name}",
        "name": name,
        "kind": kind,
        "tier": tier,
        "status": status,
        "issue": issue,
        "ref": {
            "name": "refs/remotes/origin/HEAD",
            "commit": "a" * 40,
            "shallow": False,
            "fetched_at": NOW_TS - 2 * 3600,
        },
        "output": {
            "commits": commits,
            "agent_commits": max(0, commits - 1),
            "agent_share": (max(0, commits - 1) / commits) if commits else 0.0,
        },
        "lifetime": {
            "first_commit_ts": int(datetime(2026, 2, 14, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 240,
            "age_days": 245,
            "active_days": 239,
            "commits": commits * 40 if commits else 12,
        },
        "snapshot": {
            "tracked_files": files,
            "tracked_lines": lines,
            "test_lines": None if lines is None else int(lines * 0.4),
            "doc_lines": None if lines is None else int(lines * 0.05),
            "lifetime_commits": commits * 40 if commits else 12,
            "first_commit_ts": int(datetime(2026, 2, 14, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 240,
        },
    }


def _sase_project(**overrides: object) -> dict:
    models = _models()
    project = {
        "key": "gh_sase-org__sase",
        "label": "sase",
        "state": "enabled",
        "output": _output(412, 61, models),
        "lifetime": {
            "first_commit_ts": int(datetime(2026, 2, 14, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 240,
            "age_days": 245,
            "active_days": 239,
            "commits": 17755,
            "agent_commits": 17000,
        },
        "code": _code(
            lines=3_126_927, tests=1_438_386, docs=82_000, configured=7, measured=6
        ),
        "runs": _runs(
            runs=233, completed=189, failed=31, seconds=41 * 3600, patches=18
        ),
        "repos": [
            _repo(
                name="sase", kind="primary", tier="code", commits=380, lines=3_000_000
            ),
            _repo(
                name="sase-core", kind="linked", tier="code", commits=32, lines=126_927
            ),
            _repo(
                name="missing",
                kind="linked",
                tier="code",
                status="unavailable",
                commits=0,
                issue={
                    "code": "not_cloned",
                    "message": "not cloned",
                    "project": "gh_sase-org__sase",
                    "repo": "missing",
                },
                files=None,
                lines=None,
            ),
            _repo(
                name="beads",
                kind="sidecar",
                tier="records",
                commits=12,
                files=400,
                lines=None,
            ),
        ],
        "not_counted": [{"name": "chezmoi", "reason": "user_linked"}],
        "models": models,
        "patches": [
            {
                "name": "stats-report",
                "status": "Ready",
                "has_pr": True,
                "runs": 12,
                "completed": 10,
                "failed": 2,
                "run_commits": 8,
                "total_runtime_seconds": 7200,
                "last_run_ts": NOW_TS - 240,
            },
            {
                "name": "bead-cli",
                "status": "Merged",
                "has_pr": True,
                "runs": 8,
                "completed": 8,
                "failed": 0,
                "run_commits": 5,
                "total_runtime_seconds": 3600,
                "last_run_ts": NOW_TS - 3600,
            },
        ],
        "truncated_patch_rows": 2,
        "coverage": _coverage(),
    }
    project.update(overrides)
    return project


def _bob_project() -> dict:
    models = [
        {
            "kind": "resolved",
            "provider": "muse",
            "model": "auto",
            "commits": 41,
            "plans": 10,
            "plans_epic": 2,
            "plans_tale": 8,
        },
        {
            "kind": "resolved",
            "provider": "codex",
            "model": "gpt-6-luna",
            "commits": 42,
            "plans": 6,
            "plans_epic": 1,
            "plans_tale": 5,
        },
        {"kind": "unknown", "commits": 4, "plans": 0},
        {"kind": "no_agent", "commits": 2, "plans": 0},
    ]
    return {
        "key": "bob-cli",
        "label": "bob-cli",
        "state": "enabled",
        "output": _output(89, 16, models),
        "lifetime": {
            "first_commit_ts": int(datetime(2026, 5, 1, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 3600,
            "age_days": 168,
            "active_days": 90,
            "commits": 900,
        },
        "code": _code(
            lines=369_231, tests=132_923, docs=8_000, configured=2, measured=2
        ),
        "runs": _runs(runs=170, completed=150, failed=20, seconds=22 * 3600, patches=9),
        "repos": [
            _repo(
                name="bob-cli", kind="primary", tier="code", commits=89, lines=369_231
            )
        ],
        "models": models,
        "patches": [
            {
                "name": "vault-sync",
                "status": "Merged",
                "has_pr": False,
                "runs": 6,
                "completed": 6,
                "failed": 0,
                "run_commits": 4,
                "total_runtime_seconds": 1800,
                "last_run_ts": NOW_TS - 3600,
            }
        ],
        "coverage": _coverage(),
    }


def _portfolio(projects: list[dict]) -> dict:
    commits = sum(
        (project.get("output") or {}).get("commits") or 0 for project in projects
    )
    plans = 0
    for project in projects:
        value = (project.get("output") or {}).get("plans_committed")
        if value:
            plans += value
    models = []
    for project in projects:
        models.extend(project.get("models") or [])
    collapsed: dict[tuple, dict] = {}
    for row in models:
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
    runs = sum((project.get("runs") or {}).get("runs") or 0 for project in projects)
    completed = sum(
        (project.get("runs") or {}).get("completed") or 0 for project in projects
    )
    seconds = sum(
        (project.get("runs") or {}).get("total_runtime_seconds") or 0
        for project in projects
    )
    return {
        "output": _output(commits, plans, list(collapsed.values())),
        "lifetime": {"commits": 18655, "age_days": 245, "last_commit_ts": NOW_TS - 240},
        "code": _code(
            lines=code_lines,
            tests=test_lines,
            docs=90_000,
            configured=9,
            measured=8,
        ),
        "runs": _runs(
            runs=runs,
            completed=completed,
            failed=runs - completed,
            seconds=seconds,
            patches=27,
        ),
        "models": list(collapsed.values()),
        "coverage": (
            projects[0].get("coverage") or _coverage()
            if len(projects) == 1
            else _coverage()
        ),
    }


def build_view(
    *,
    projects: list[dict] | None = None,
    facets: set[str] | None = None,
    group_by: str | None = None,
    project_refs: tuple[str, ...] = (),
) -> ProjectStatsView:
    rows = projects if projects is not None else [_sase_project(), _bob_project()]
    wire = {
        "schema_version": 1,
        "metric_policy_version": 1,
        "classifier_version": 1,
        "engine_version": 1,
        "range": {"start_ts": RANGE.start_ts, "end_ts": RANGE.end_ts},
        "fingerprint": "golden",
        "projects": rows,
        "portfolio": _portfolio(rows),
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
    return build_view(projects=[_sase_project()], project_refs=("sase",), **kwargs)


def all_projects_view(**kwargs: object) -> ProjectStatsView:
    return build_view(**kwargs)


def empty_range_view() -> ProjectStatsView:
    empty_output = _output(0, 0, [])
    empty_output["plans_committed"] = 0
    project = _sase_project(
        output=empty_output,
        models=[],
        runs=_runs(runs=0, completed=0, failed=0, seconds=0, patches=0),
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
    return build_view(projects=[project], project_refs=("sase",))


def local_plans_view() -> ProjectStatsView:
    output = _output(412, 0, _models())
    output["plans_committed"] = None
    output["plans_epic"] = None
    output["plans_tale"] = None
    return build_view(projects=[_sase_project(output=output)], project_refs=("sase",))


def code_pending_view() -> ProjectStatsView:
    project = _sase_project(code=None)
    return build_view(
        projects=[project],
        project_refs=("sase",),
        facets={"output", "runs"},
    )
