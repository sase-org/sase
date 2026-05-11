"""Tests for status-string canonicalization during revive."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._revive import AgentRevivalMixin

from tests._agent_revive_helpers import make_agent


@pytest.mark.parametrize(
    ("display_status", "canonical"),
    [
        ("DONE", "completed"),
        ("PLAN DONE", "completed"),
        ("TALE DONE", "completed"),
        ("PLAN COMMITTED", "completed"),
        ("EPIC APPROVED", "completed"),
        ("EPIC CREATED", "completed"),
        ("FAILED", "failed"),
        ("WAITING INPUT", "waiting_hitl"),
        ("RUNNING", "running"),
    ],
)
def test_build_workflow_state_data_canonicalizes_statuses(
    display_status: str, canonical: str
) -> None:
    agent = make_agent(status=display_status)
    data = AgentRevivalMixin._build_workflow_state_data(agent)
    assert data["status"] == canonical


@pytest.mark.parametrize(
    ("display_status", "canonical"),
    [
        ("DONE", "completed"),
        ("PLAN DONE", "completed"),
        ("TALE DONE", "completed"),
        ("PLAN COMMITTED", "completed"),
        ("EPIC CREATED", "completed"),
        ("FAILED", "failed"),
        ("WAITING INPUT", "waiting_hitl"),
        ("RUNNING", "in_progress"),
    ],
)
def test_build_step_marker_data_canonicalizes_statuses(
    display_status: str, canonical: str
) -> None:
    agent = make_agent(status=display_status)
    data = AgentRevivalMixin._build_step_marker_data(agent)
    assert data["status"] == canonical
