import json
from pathlib import Path

import pytest

from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.stats.query import query_activity_stats, query_run_stats
from sase.stats.views import build_statistics_views


def test_statistics_facade_smoke_through_real_bindings(tmp_path: Path) -> None:
    extension = pytest.importorskip("sase_core_rs")
    required = {
        "agent_stats_query_runs",
        "agent_stats_query_activity",
        "rebuild_agent_artifact_index",
    }
    if not required.issubset(dir(extension)):
        pytest.skip("installed sase_core_rs predates the agent statistics bindings")

    projects = tmp_path / "projects"
    project = projects / "proj"
    artifact = project / "artifacts" / "ace-run" / "20260710010000"
    artifact.mkdir(parents=True)
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "smoke-agent",
                "run_started_at": "100",
                "llm_provider": "codex",
                "model": "gpt-5",
                "reasoning_effort": "high",
            }
        ),
        encoding="utf-8",
    )
    (artifact / "done.json").write_text(
        json.dumps({"outcome": "completed", "finished_at": 160.0}),
        encoding="utf-8",
    )
    (project / "skill_uses.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "120",
                "skill_name": "review",
                "agent_name": "smoke-agent",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    index = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index, projects)

    runs = query_run_stats(
        start_ts=0,
        end_ts=200,
        bucket_seconds=100,
        index_path=index,
    )
    activity = query_activity_stats(
        start_ts=0,
        end_ts=200,
        index_path=index,
        home_path=tmp_path,
    )

    assert runs["totals"]["runs"] == 1
    assert runs["providers"][0]["effort"] == "high"
    if "work" not in runs:
        pytest.skip("installed sase_core_rs predates work statistics schema v2")
    assert runs["work"]["projects"][0]["project"] == "proj"
    assert runs["work"]["unattributed_runs"] == 1
    assert activity["skills"] == [{"name": "review", "count": 1, "distinct_agents": 1}]

    if runs.get("schema_version", 0) < 3 or "runners" not in runs:
        pytest.skip("installed sase_core_rs predates runner occupancy schema v3")
    runners = build_statistics_views(runs, activity, current_runner_limit=8).runners
    assert runners.available is True
    assert runners.peak_runners == 1
    assert runners.current_limit == 8
    assert [row.runners for row in runners.distribution] == [0, 1]
    assert sum(row.seconds for row in runners.distribution) == pytest.approx(
        runners.end_ts - runners.start_ts
    )
    assert runners.trend and runners.trend[0].peak_runners == 1
