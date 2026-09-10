"""Tests for the Agents-tab profile query row adapter."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sase.ace.query.profile_reference import (
    ProfileQueryError,
    evaluate_query_many_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import agents_live_query_schema, compile_query_profile
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_live_query import (
    agent_live_query_entry,
    agent_live_query_row_id,
)

_NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)


class _FakeContentCache:
    def __init__(self, haystack: str) -> None:
        self.haystack = haystack
        self.calls: list[tuple[AgentType, str, str | None]] = []

    def get_haystack(self, agent: Agent) -> str:
        self.calls.append(agent.identity)
        return self.haystack


def _agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "sase-zf",
        "project_file": "/tmp/projects/sase/project.yml",
        "status": "RUNNING",
        "start_time": _NOW - timedelta(minutes=30),
        "run_start_time": _NOW - timedelta(minutes=30),
        "agent_name": "sase-zf.1--code",
    }
    defaults.update(overrides)
    return Agent(**defaults)


def _match_ids(
    query: str,
    rows: Iterable[dict[str, Any]],
) -> tuple[str, ...]:
    profile = compile_query_profile(agents_live_query_schema())
    materialized = tuple(rows)
    matches = evaluate_query_many_for_profile(query, materialized, profile)
    return tuple(
        row["stable_id"]
        for row, matched in zip(materialized, matches, strict=True)
        if matched
    )


def test_agent_live_query_entry_projects_every_live_derived_field() -> None:
    start = datetime(2026, 8, 24, 10, 0, 0, tzinfo=UTC)
    run_start = start + timedelta(minutes=5)
    stop = start + timedelta(minutes=15)
    agent = _agent(
        cl_name="sase-zf",
        project_file="/tmp/projects/gh_sase-org__sase/project.yml",
        project_display_name="sase",
        status="QUESTION",
        start_time=start,
        run_start_time=run_start,
        stop_time=stop,
        questions_times=[stop],
        agent_family="sase-zf.1",
        agent_family_role="code",
        role_suffix="--code",
        agent_clan="athena.sase-zf",
        tribe="pinned",
        workflow="review",
        model="gpt-5.6-sol",
        llm_provider="Codex",
        retry_attempt=2,
        retry_of_timestamp="20260824100000",
        hidden=True,
        source_machine="athena",
    )
    cache = _FakeContentCache("cached transcript CaseNeedle")

    entry = agent_live_query_entry(
        agent,
        content_cache=cache,
        unread_agent_ids={agent.identity},
        now=_NOW,
    )
    fields = entry["fields"]

    assert entry["stable_id"] == "sase-zf.1--code"
    assert "sase-zf.1--code" in fields["name"]
    assert fields["kind"] == ("agent",)
    assert fields["family"] == ("sase-zf.1",)
    assert fields["clan"] == ("athena.sase-zf",)
    assert fields["project"] == ("gh_sase-org__sase", "sase")
    assert fields["role"] == ("code",)
    assert fields["workflow"] == ("review",)
    assert fields["model"] == ("gpt-5.6-sol",)
    assert fields["provider"] == ("codex",)
    assert fields["status"] == ("QUESTION",)
    assert fields["attempt"] == (2,)
    assert fields["hidden"] == (True,)
    assert fields["attention"] == (True,)
    assert fields["retry"] == (True,)
    assert fields["machine"] == ("here", "athena")
    assert fields["tribe"] == ("pinned",)
    assert fields["pinned"] == (True,)
    assert fields["unread"] == (True,)
    assert fields["needs"] == ("input",)
    assert fields["source"] == ("axe",)
    assert fields["since"] == (int(start.timestamp()),)
    assert fields["until"] == (int(start.timestamp()),)
    assert fields["after"] == (int(stop.timestamp()),)
    assert fields["before"] == (int(stop.timestamp()),)
    assert fields["min"] == (600,)
    assert fields["max"] == (600,)
    assert fields["cl"] == ("sase-zf",)
    assert "cached transcript CaseNeedle" in fields["text"]
    assert "cached transcript CaseNeedle" in entry["searchable_text"]
    assert cache.calls == [agent.identity]


def test_agent_live_query_entry_projects_remote_machine_alias_and_hostnames() -> None:
    agent = _agent(
        agent_name="remote-run",
        status="RUNNING",
        fleet_origin_alias="Apollo",
        fleet_logical_locator={
            "machine_name": "apollo.local",
            "project": {"project_id": "remote-proj", "name": "Remote Project"},
        },
        fleet_exact_locator={
            "host": {"hostname": "apollo.internal"},
            "origin": {"machine_name": "apollo-origin"},
        },
        source_machine="apollo-source",
    )

    entry = agent_live_query_entry(agent, now=_NOW)
    fields = entry["fields"]

    assert fields["machine"] == (
        "Apollo",
        "apollo.local",
        "apollo.internal",
        "apollo-origin",
        "apollo-source",
    )
    assert fields["project"] == (
        "sase",
        "remote-proj",
        "Remote Project",
    )
    assert _match_ids("machine:apollo.local AND source:manual", (entry,)) == (
        "remote-run",
    )


def test_agent_live_query_entry_classifies_container_and_workflow_kinds() -> None:
    family_child = _agent(agent_name="family-root--code", raw_suffix="child")
    family = _agent(
        agent_name="family-root",
        agent_family="family-root",
        agent_family_role="root",
        plan_chain_root=True,
        followup_agents=[family_child],
    )
    clan = _agent(
        agent_name="athena.sase-zf",
        agent_clan="athena.sase-zf",
        agent_clan_generation="1",
        is_clan_container=True,
    )
    workflow_child = _agent(
        agent_type=AgentType.WORKFLOW,
        agent_name="workflow-step",
        parent_workflow="outer",
        step_type="agent",
    )
    workflow_member = _agent(
        agent_type=AgentType.WORKFLOW,
        agent_name="workflow-member",
        workflow="inner",
        parent_timestamp="20260824100000",
    )

    assert agent_live_query_entry(family, now=_NOW)["fields"]["kind"] == ("family",)
    assert agent_live_query_entry(clan, now=_NOW)["fields"]["kind"] == ("clan",)
    assert agent_live_query_entry(workflow_child, now=_NOW)["fields"]["kind"] == (
        "member",
        "workflow-child",
    )
    assert agent_live_query_entry(workflow_member, now=_NOW)["fields"]["kind"] == (
        "member",
        "workflow",
    )


def test_agent_live_query_entry_matches_profile_queries_and_transcript_corpus() -> None:
    input_agent = _agent(
        agent_name="input-agent",
        status="QUESTION",
        questions_times=[_NOW],
        workflow="review",
        tribe="pinned",
    )
    remote_agent = _agent(
        agent_name="remote-agent",
        status="RUNNING",
        fleet_origin_alias="apollo",
        fleet_logical_locator={"machine_name": "apollo.local"},
    )
    rows = (
        agent_live_query_entry(
            input_agent,
            content_cache=_FakeContentCache("transcript body CaseNeedle"),
            unread_agent_ids={input_agent.identity},
            now=_NOW,
        ),
        agent_live_query_entry(remote_agent, now=_NOW),
    )

    assert _match_ids(
        "machine:here AND pinned:true AND unread:true AND needs:input", rows
    ) == ("input-agent",)
    assert _match_ids('source:axe AND c"CaseNeedle"', rows) == ("input-agent",)
    assert _match_ids("machine:apollo.local AND source:manual", rows) == (
        "remote-agent",
    )


def test_agent_live_query_row_id_falls_back_to_agent_identity() -> None:
    agent = _agent(agent_name=None, raw_suffix="20260824100000")

    assert agent_live_query_row_id(agent) == "run:sase-zf:20260824100000"


def test_agents_live_profile_rejects_removed_legacy_row_adapter_terms() -> None:
    profile = compile_query_profile(agents_live_query_schema())

    for query in ("age:2h", "age>2h", "type:run", "type:workflow"):
        with pytest.raises(ProfileQueryError):
            parse_query_for_profile(query, profile)
