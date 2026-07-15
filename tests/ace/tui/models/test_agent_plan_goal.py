"""Plan-goal association and cache tests for Agents-tab enrichment."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_plan_goal as plan_goal_model
from sase.ace.tui.models.agent_plan_goal import resolve_agent_plan_goal
from sase.agent.bead_display import BeadIssueLookupSession
from sase.bead.model import Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_goal_caches() -> Iterator[None]:
    plan_goal_model._PLAN_GOAL_CACHE.clear()
    plan_goal_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_goal_model._PLAN_GOAL_CACHE.clear()
    plan_goal_model._PLAN_ASSOCIATION_CACHE.clear()


def _write_plan(path: Path, goal: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntier: tale\ngoal: {goal!r}\n---\n# Plan\n")
    return path


def test_resolves_direct_plan_path_before_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "direct.md", "Deliver the direct plan")
    agent = make_agent(
        plan_path=str(plan),
        epic_bead_id="sase-1",
        workspace_dir=str(tmp_path),
    )

    def unexpected_lookup(*_args: object, **_kwargs: object) -> Issue | None:
        raise AssertionError("direct plan metadata must win")

    monkeypatch.setattr(plan_goal_model, "_lookup_issue", unexpected_lookup)

    assert resolve_agent_plan_goal(agent) == "Deliver the direct plan"


def test_resolves_epic_bead_design(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_plan(tmp_path / "plans" / "epic.md", "Land every epic phase")
    agent = make_agent(agent_name="sase-1", workspace_dir=str(tmp_path))
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        design="plans/epic.md",
    )
    monkeypatch.setattr(
        plan_goal_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: epic if bead_id == epic.id else None,
    )

    with BeadIssueLookupSession() as lookup_session:
        assert (
            resolve_agent_plan_goal(agent, lookup_session=lookup_session)
            == "Land every epic phase"
        )


def test_resolves_phase_bead_through_parent_design(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_plan(tmp_path / "plans" / "epic.md", "Complete the parent outcome")
    agent = make_agent(phase_bead_id="sase-1.2", workspace_dir=str(tmp_path))
    phase = Issue(id="sase-1.2", title="Phase", parent_id="sase-1")
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        design="plans/epic.md",
    )
    issues = {phase.id: phase, epic.id: epic}
    lookups: list[str] = []

    def lookup(_agent: object, bead_id: str, **_kwargs: object) -> Issue | None:
        lookups.append(bead_id)
        return issues.get(bead_id)

    monkeypatch.setattr(plan_goal_model, "_lookup_issue", lookup)

    with BeadIssueLookupSession() as lookup_session:
        assert (
            resolve_agent_plan_goal(agent, lookup_session=lookup_session)
            == "Complete the parent outcome"
        )
    assert lookups == ["sase-1.2", "sase-1"]


def test_returns_none_without_plan_association() -> None:
    assert resolve_agent_plan_goal(make_agent(agent_name="utility")) is None


def test_returns_none_for_missing_plan_file(tmp_path: Path) -> None:
    agent = make_agent(
        plan_path=str(tmp_path / "missing.md"),
        workspace_dir=str(tmp_path),
    )

    assert resolve_agent_plan_goal(agent) is None


def test_goal_cache_reuses_read_until_plan_mtime_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "cached.md", "First goal")
    agent = make_agent(plan_path=str(plan), workspace_dir=str(tmp_path))
    real_reader = plan_goal_model.read_plan_goal
    reads: list[Path] = []

    def read(path: Path) -> str | None:
        reads.append(path)
        return real_reader(path)

    monkeypatch.setattr(plan_goal_model, "read_plan_goal", read)

    assert resolve_agent_plan_goal(agent) == "First goal"
    assert resolve_agent_plan_goal(agent) == "First goal"
    assert reads == [plan.resolve()]

    previous_mtime = plan.stat().st_mtime_ns
    _write_plan(plan, "Second, updated goal")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    assert resolve_agent_plan_goal(agent) == "Second, updated goal"
    assert reads == [plan.resolve(), plan.resolve()]
