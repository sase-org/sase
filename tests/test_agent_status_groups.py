"""Integration-facing agent status grouping helpers."""

from __future__ import annotations

from sase.agent.running import RunningAgentInfo
from sase.integrations.agent_status_groups import (
    agent_status_bucket,
    group_agent_statuses,
)


def _agent(
    name: str,
    status: str,
    *,
    retried_as_timestamp: str | None = None,
) -> RunningAgentInfo:
    info = RunningAgentInfo(
        name=name,
        project="proj",
        pid=123,
        model="opus",
        provider="claude",
        workspace_num=1,
        duration="5m",
        approve=False,
        prompt="prompt",
        status=status,
    )
    if retried_as_timestamp is not None:
        info.retried_as_timestamp = retried_as_timestamp
    return info


def test_agent_status_bucket_running() -> None:
    assert agent_status_bucket(_agent("a", "RUNNING")) == "Running"


def test_agent_status_bucket_waiting() -> None:
    assert agent_status_bucket(_agent("a", "WAITING")) == "Waiting"


def test_agent_status_bucket_question() -> None:
    assert agent_status_bucket(_agent("a", "QUESTION")) == "Needs Attention"


def test_agent_status_bucket_failed_without_retry() -> None:
    assert agent_status_bucket(_agent("a", "FAILED")) == "Needs Attention"


def test_agent_status_bucket_failed_with_retry() -> None:
    assert (
        agent_status_bucket(_agent("a", "FAILED", retried_as_timestamp="child-ts"))
        == "Failed"
    )


def test_agent_status_bucket_done() -> None:
    assert agent_status_bucket(_agent("a", "DONE")) == "Done"


def test_group_agent_statuses_omits_empty_buckets_and_preserves_order() -> None:
    groups = group_agent_statuses(
        [
            _agent("run-1", "RUNNING"),
            _agent("done-1", "DONE"),
            _agent("run-2", "RUNNING"),
            _agent("question-1", "QUESTION"),
        ]
    )

    assert [group.bucket for group in groups] == [
        "Needs Attention",
        "Running",
        "Done",
    ]
    assert [[agent.name for agent in group.agents] for group in groups] == [
        ["question-1"],
        ["run-1", "run-2"],
        ["done-1"],
    ]
