"""Exercise real project-statistics wire integration against an isolated Git repo."""

import os
from pathlib import Path
import subprocess

from sase.core.project_stats_facade import query_project_stats
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.project import ProjectStatsQuery
from sase.stats.project.view import build_project_stats_view
from sase.stats.ranges import StatsRange


def test_project_binding_counts_root_sidecar_plans_and_preserves_unknowns(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (repo / "plan.md").write_text(
        "---\ntitle: A plan\ntier: epic\nproposed_with: openai/gpt\n---\nA plan.\n"
    )
    git("add", ".")
    git("commit", "-m", "feat: add a plan\n\nSASE_AGENT=test\nSASE_MODEL=openai/gpt")
    request = {
        "schema_version": 1,
        "start_ts": 0,
        "end_ts": 4_000_000_000,
        "now_ts": 4_000_000_000,
        "timezone": "UTC",
        "facets": ["output"],
        "cache_dir": str(tmp_path / "cache"),
        "projects": [
            {
                "key": "alpha",
                "label": "Alpha Project",
                "state": "enabled",
                "code_repos": [
                    {
                        "id": "primary",
                        "name": "alpha",
                        "kind": "primary",
                        "path": str(repo),
                        "ref_candidates": ["HEAD"],
                    }
                ],
                "plan_store": {
                    "storage": "sidecar_repos",
                    "repo_path": str(repo),
                    "plans_dir": ".",
                },
            }
        ],
    }
    cold = query_project_stats(request)
    warm = query_project_stats(request)
    assert cold == warm
    view = build_project_stats_view(
        cold,
        ProjectStatsQuery(range=StatsRange(0, 4_000_000_000, "all", "All")),
        machine="test",
        generated_at="fixed",
        timezone="UTC",
        facets={"output"},
        display_snapshot=ProjectDisplaySnapshot(),
    )
    assert view.projects[0].output.commits == 1
    assert view.projects[0].output.plans_committed == 1
    assert view.projects[0].lifetime.commits == 1
    assert view.projects[0].code is None
    assert {row.kind for row in view.models} >= {"unknown", "no_agent"}
    assert sum(row.commits for row in view.models) == 1
    assert view.repos[0].ref.commit == git("rev-parse", "HEAD")
    assert view.data == cold
