"""Shared constants and row builders for project render fixtures."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

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


def models() -> list[dict]:
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


def coverage() -> dict:
    return {
        "configured_repos": 7,
        "measured_repos": 6,
        "unavailable_repos": 1,
        "agent_tagged_commits": 408,
        "resolved_agent_commits": 381,
        "unknown_agent_commits": 27,
        "unknown_reasons": [{"reason": "page_unpublished", "count": 27}],
    }


def output(commits: int, plans: int, models: list[dict]) -> dict:
    agent = sum(row["commits"] for row in models if row["kind"] != "no_agent")
    return {
        "commits": commits,
        "agent_commits": agent,
        "agent_share": agent / commits if commits else 0.0,
        "plans_committed": plans,
        "plans_epic": sum(row.get("plans_epic") or 0 for row in models),
        "plans_tale": sum(row.get("plans_tale") or 0 for row in models),
        "models": models,
        "commit_coverage": coverage(),
        "plan_coverage": coverage(),
    }


def code(
    *,
    lines: int,
    tests: int,
    docs: int,
    configured: int,
    measured: int,
    languages: list[dict] | None = None,
    files: int | None = None,
) -> dict:
    if languages is None:
        languages = [{"name": "python", "files": 12, "lines": lines}]
    if files is None:
        files = sum(row["files"] for row in languages)
    return {
        "counter": "sloc",
        "code_lines": lines,
        "code_files": files,
        "test_lines": tests,
        "test_share": tests / lines if lines else None,
        "doc_lines": docs,
        "repos_configured": configured,
        "repos_measured": measured,
        "languages": languages,
    }


def runs(
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


def repo(
    *,
    name: str,
    kind: str,
    tier: str,
    status: str = "ok",
    commits: int = 0,
    issue: dict | None = None,
    files: int | None = 10,
    lines: int | None = 1000,
    languages: list[dict] | None = None,
    unknown_lines: int = 0,
    unknown_files: int = 0,
) -> dict:
    if languages is None and lines is not None and tier == "code" and status == "ok":
        languages = (
            [{"name": "python", "files": files or 0, "lines": lines}]
            if (lines or 0) > 0
            else []
        )
    lang_lines = sum(row["lines"] for row in (languages or []))
    lang_files = sum(row["files"] for row in (languages or []))
    if tier == "code" and status == "ok" and lines is not None:
        code_lines = lang_lines + unknown_lines
        code_files = lang_files + unknown_files
        # Keep legacy tracked_* for the pre-fix inconsistency: tracked counts
        # every role while code counts source + tests only.
        doc_lines = int(code_lines * 0.05)
        tracked_lines = code_lines + doc_lines + 500
        tracked_files = code_files + 5
        test_lines = int(code_lines * 0.4)
        source_lines = code_lines - test_lines
        source_files = code_files - int(code_files * 0.4)
        test_files = code_files - source_files
        role_counts = [
            {"role": "source", "files": source_files, "lines": source_lines},
            {"role": "tests", "files": test_files, "lines": test_lines},
            {"role": "docs", "files": 5, "lines": doc_lines},
            {"role": "other", "files": 2, "lines": 500},
        ]
    else:
        code_lines = lines
        code_files = files
        tracked_lines = lines
        tracked_files = files
        test_lines = None if lines is None else int(lines * 0.4)
        doc_lines = None if lines is None else int(lines * 0.05)
        role_counts = None
    result = {
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
            "tracked_files": tracked_files,
            "tracked_lines": tracked_lines,
            "test_lines": test_lines,
            "doc_lines": doc_lines,
            "lifetime_commits": commits * 40 if commits else 12,
            "first_commit_ts": int(datetime(2026, 2, 14, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 240,
            "languages": languages,
            "role_counts": role_counts,
        },
    }
    if status == "unavailable":
        result["output"] = None
        result["lifetime"] = None
        result["snapshot"] = None
    return result
