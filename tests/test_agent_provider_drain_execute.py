"""Execution applies each move sequentially and never aborts for one failure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.agent._drain_types import DrainRoute, ProviderDrainMove, ProviderDrainPlan
from sase.agent.provider_drain import execute_provider_drain
from sase.agent.restart import AgentRestartOutcome
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests._agent_restart_helpers import dummy_plan, failed_kill, successful_kill


def _disable() -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=2,
        provider="claude",
        created_at=1_800_000_000.0,
        expires_at=None,
        source="test",
        mode="hard",
    )


def _move(tmp_path: Path, name: str) -> ProviderDrainMove:
    restart_plan = dummy_plan(tmp_path / name, name=name)
    route = DrainRoute(kind="reroute", target_provider="codex", target_model="gpt-5")
    return ProviderDrainMove(
        name=name,
        presented_name=name,
        project="gh_sase-org__sase",
        status="RUNNING",
        route=route,
        restart_plan=restart_plan,
    )


def _plan_with_moves(moves: list[ProviderDrainMove]) -> ProviderDrainPlan:
    return ProviderDrainPlan(
        provider="claude",
        disable=_disable(),
        moves=tuple(moves),
        skips=(),
        model_override=None,
        limit=20,
    )


def test_runs_each_move_sequentially_and_collects_outcomes(tmp_path: Path) -> None:
    move_a = _move(tmp_path, "agent-a")
    move_b = _move(tmp_path, "agent-b")
    plan = _plan_with_moves([move_a, move_b])

    outcome_a = AgentRestartOutcome(
        status="ok", name="agent-a", stop_action="killed", stop_result=successful_kill()
    )
    outcome_b = AgentRestartOutcome(
        status="kill_failed",
        name="agent-b",
        stop_action="killed",
        stop_result=failed_kill(),
        error="boom",
    )
    calls: list[str] = []

    def fake_execute(restart_plan, *, progress=None):
        calls.append(restart_plan.name)
        return outcome_a if restart_plan.name == "agent-a" else outcome_b

    with patch("sase.agent.restart.execute_agent_restart", side_effect=fake_execute):
        result = execute_provider_drain(plan)

    assert calls == ["agent-a", "agent-b"]
    assert result.results == (outcome_a, outcome_b)


def test_a_failed_move_does_not_abort_remaining_moves(tmp_path: Path) -> None:
    move_a = _move(tmp_path, "agent-a")
    move_b = _move(tmp_path, "agent-b")
    move_c = _move(tmp_path, "agent-c")
    plan = _plan_with_moves([move_a, move_b, move_c])

    def fake_execute(restart_plan, *, progress=None):
        if restart_plan.name == "agent-b":
            return AgentRestartOutcome(
                status="wipe_failed",
                name="agent-b",
                stop_action="killed",
                stop_result=successful_kill(),
                error="name wipe exploded",
            )
        return AgentRestartOutcome(
            status="ok",
            name=restart_plan.name,
            stop_action="killed",
            stop_result=successful_kill(),
        )

    with patch("sase.agent.restart.execute_agent_restart", side_effect=fake_execute):
        result = execute_provider_drain(plan)

    assert [r.name for r in result.results] == ["agent-a", "agent-b", "agent-c"]
    assert result.relaunched == 2
    assert result.failed == 1


def test_relaunched_and_failed_counts_reflect_ok_versus_other_statuses(
    tmp_path: Path,
) -> None:
    move_a = _move(tmp_path, "agent-a")
    move_b = _move(tmp_path, "agent-b")
    plan = _plan_with_moves([move_a, move_b])

    def fake_execute(restart_plan, *, progress=None):
        status = "ok" if restart_plan.name == "agent-a" else "partial"
        return AgentRestartOutcome(
            status=status,
            name=restart_plan.name,
            stop_action="killed",
            stop_result=successful_kill(),
        )

    with patch("sase.agent.restart.execute_agent_restart", side_effect=fake_execute):
        result = execute_provider_drain(plan)

    assert result.relaunched == 1
    assert result.failed == 1


def test_empty_plan_executes_nothing() -> None:
    plan = _plan_with_moves([])
    with patch("sase.agent.restart.execute_agent_restart") as mocked:
        result = execute_provider_drain(plan)
    mocked.assert_not_called()
    assert result.results == ()
    assert result.relaunched == 0
    assert result.failed == 0


def test_progress_callback_is_forwarded_to_each_restart(tmp_path: Path) -> None:
    move = _move(tmp_path, "agent-a")
    plan = _plan_with_moves([move])
    events: list[tuple[str, str, str]] = []

    def progress(step: str, status: str, detail: str) -> None:
        events.append((step, status, detail))

    def fake_execute(restart_plan, *, progress=None):
        assert progress is not None
        progress("stopped", "ok", "done")
        return AgentRestartOutcome(
            status="ok",
            name=restart_plan.name,
            stop_action="killed",
            stop_result=successful_kill(),
        )

    with patch("sase.agent.restart.execute_agent_restart", side_effect=fake_execute):
        execute_provider_drain(plan, progress=progress)

    assert events == [("stopped", "ok", "done")]
