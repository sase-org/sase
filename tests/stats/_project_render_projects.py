"""Pinned project rows for project render fixtures."""

from __future__ import annotations

from datetime import datetime

from tests.stats._project_render_base import (
    NOW_TS,
    TZ,
    code,
    coverage,
    models,
    output,
    repo,
    runs,
)


def sase_project(**overrides: object) -> dict:
    project_models = models()
    sase_languages = [
        {"name": "python", "files": 12000, "lines": 2_450_000},
        {"name": "css", "files": 6, "lines": 10_131},
        {"name": "json", "files": 20, "lines": 5_000},
        {"name": "bash", "files": 10, "lines": 1_000},
        {"name": "diff", "files": 3, "lines": 0},
    ]
    project = {
        "key": "gh_sase-org__sase",
        "label": "sase",
        "state": "enabled",
        "output": output(412, 61, project_models),
        "lifetime": {
            "first_commit_ts": int(datetime(2026, 2, 14, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 240,
            "age_days": 245,
            "active_days": 239,
            "commits": 17755,
            "agent_commits": 17000,
        },
        "code": code(
            lines=3_137_590,
            tests=1_438_386,
            docs=82_000,
            configured=7,
            measured=6,
            languages=[
                {"name": "python", "files": 12570, "lines": 2_565_000},
                {"name": "rust", "files": 1100, "lines": 550_000},
                {"name": "css", "files": 7, "lines": 10_167},
                {"name": "lua", "files": 29, "lines": 4_389},
                {"name": "json", "files": 20, "lines": 5_000},
                {"name": "bash", "files": 10, "lines": 1_000},
                {"name": "sh", "files": 10, "lines": 500},
                {"name": "jinja", "files": 5, "lines": 300},
                {"name": "diff", "files": 3, "lines": 0},
            ],
            files=13_765,
        ),
        "runs": runs(runs=233, completed=189, failed=31, seconds=41 * 3600, patches=18),
        "repos": [
            repo(
                name="sase",
                kind="primary",
                tier="code",
                commits=380,
                languages=sase_languages,
                unknown_lines=1_000,
                unknown_files=9,
            ),
            repo(
                name="sase-core",
                kind="linked",
                tier="code",
                commits=32,
                languages=[
                    {"name": "rust", "files": 1100, "lines": 550_000},
                    {"name": "python", "files": 300, "lines": 50_000},
                ],
            ),
            repo(
                name="sase-telegram",
                kind="linked",
                tier="code",
                commits=0,
                languages=[
                    {"name": "python", "files": 90, "lines": 30_000},
                    {"name": "css", "files": 1, "lines": 36},
                ],
            ),
            repo(
                name="sase-listen",
                kind="linked",
                tier="code",
                commits=0,
                languages=[
                    {"name": "python", "files": 90, "lines": 20_000},
                    {"name": "sh", "files": 10, "lines": 500},
                ],
                unknown_lines=234,
                unknown_files=2,
            ),
            repo(
                name="sase-nvim",
                kind="linked",
                tier="code",
                commits=0,
                languages=[
                    {"name": "lua", "files": 29, "lines": 4_389},
                    {"name": "python", "files": 40, "lines": 5_000},
                    {"name": "jinja", "files": 5, "lines": 300},
                ],
            ),
            repo(
                name="shared-lib",
                kind="linked",
                tier="code",
                commits=0,
                languages=[{"name": "python", "files": 50, "lines": 10_000}],
            ),
            repo(
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
            repo(
                name="beads",
                kind="sidecar",
                tier="records",
                commits=12,
                files=400,
                lines=None,
            ),
        ],
        "not_counted": [{"name": "chezmoi", "reason": "user_linked"}],
        "models": project_models,
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
        "coverage": coverage(),
    }
    project.update(overrides)
    return project


def bob_project() -> dict:
    project_models = [
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
        "output": output(89, 16, project_models),
        "lifetime": {
            "first_commit_ts": int(datetime(2026, 5, 1, tzinfo=TZ).timestamp()),
            "last_commit_ts": NOW_TS - 3600,
            "age_days": 168,
            "active_days": 90,
            "commits": 900,
        },
        "code": code(
            lines=349_231,
            tests=132_923,
            docs=8_000,
            configured=4,
            measured=4,
            languages=[
                {"name": "javascript", "files": 580, "lines": 220_000},
                {"name": "python", "files": 280, "lines": 69_231},
                {"name": "rust", "files": 150, "lines": 60_000},
            ],
            files=1_010,
        ),
        "runs": runs(runs=170, completed=150, failed=20, seconds=22 * 3600, patches=9),
        "repos": [
            repo(
                name="bob-cli",
                kind="primary",
                tier="code",
                commits=89,
                languages=[
                    {"name": "javascript", "files": 500, "lines": 200_000},
                    {"name": "python", "files": 200, "lines": 50_000},
                ],
            ),
            repo(
                name="bob-plugins",
                kind="linked",
                tier="code",
                commits=63,
                languages=[
                    {"name": "rust", "files": 150, "lines": 60_000},
                    {"name": "javascript", "files": 80, "lines": 20_000},
                ],
            ),
            repo(
                name="bob-mac-capture",
                kind="linked",
                tier="code",
                commits=0,
                languages=[{"name": "python", "files": 30, "lines": 9_231}],
            ),
            repo(
                name="shared-lib",
                kind="linked",
                tier="code",
                commits=0,
                languages=[{"name": "python", "files": 50, "lines": 10_000}],
            ),
        ],
        "models": project_models,
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
        "coverage": coverage(),
    }
