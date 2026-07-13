"""Tests for durable repository-open audit events."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from sase.agent.identity import AgentIdentity
from sase.repo_open_log import (
    append_repo_open_event,
    build_repo_open_event,
    filter_repo_open_events,
    read_repo_open_events,
    summarize_repo_opens_by_agent,
    summarize_repo_opens_by_repo,
)


def _event(
    *,
    repo: str = "core",
    agent_name: str = "agent-a",
    workspace_num: int = 10,
    timestamp: datetime | None = None,
):
    return build_repo_open_event(
        project="demo",
        repo=repo,
        repo_kind="linked",
        workspace_num=workspace_num,
        path=f"/work/demo_{workspace_num}/repos/{repo}",
        reason=f"open {repo}",
        cwd=Path("/work/demo_10"),
        now=timestamp or datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
        open_id=f"{agent_name}-{repo}-{workspace_num}",
        agent=AgentIdentity(agent_name, "SASE_AGENT_NAME", "/artifacts"),
    )


def test_append_and_read_skip_malformed_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "repo_opens.jsonl"
    event = _event()

    append_repo_open_event(event, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as output_file:
        output_file.write("not-json\n")
        output_file.write(json.dumps({"schema_version": 99}) + "\n")

    assert read_repo_open_events(log_path=log_path) == (event,)


def test_interactive_identity_is_best_effort() -> None:
    event = build_repo_open_event(
        project="demo",
        repo="demo",
        repo_kind="primary",
        workspace_num=0,
        path="/work/demo",
        reason="inspect checkout",
        env={},
        login_user="bryan",
    )

    assert event.agent_name == "bryan"
    assert event.agent_source == "interactive"
    assert event.artifacts_dir is None


def test_filters_and_summaries_are_deterministic() -> None:
    earlier = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    later = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)
    events = (
        _event(repo="zeta", agent_name="agent-b", timestamp=earlier),
        _event(repo="alpha", agent_name="agent-a", timestamp=earlier),
        _event(repo="alpha", agent_name="agent-b", timestamp=later),
    )

    assert filter_repo_open_events(events, repo="alpha") == events[1:]
    assert filter_repo_open_events(events, agent_name="agent-a") == (events[1],)
    assert filter_repo_open_events(events, workspace_num=10) == events

    by_repo = summarize_repo_opens_by_repo(events)
    assert [summary.repo for summary in by_repo] == ["alpha", "zeta"]
    assert by_repo[0].open_count == 2
    assert by_repo[0].distinct_agent_count == 2
    assert by_repo[0].last_agent == "agent-b"

    by_agent = summarize_repo_opens_by_agent(events)
    assert [summary.agent_name for summary in by_agent] == ["agent-a", "agent-b"]
    assert by_agent[1].open_count == 2
    assert by_agent[1].distinct_repo_count == 2
