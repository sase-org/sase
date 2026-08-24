"""Surface behavior for ``sase agent drain``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.provider_drain import (
    DrainRoute,
    ProviderDrainError,
    ProviderDrainMove,
    ProviderDrainOutcome,
    ProviderDrainPlan,
    ProviderDrainSkip,
)
from sase.agent.restart import AgentRestartOutcome
from sase.agents._drain_render import AGENT_DRAIN_JSON_SCHEMA_VERSION
from sase.agents.cli_drain import run_agents_drain
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.main.parser import create_parser
from tests._agent_restart_helpers import (
    dummy_plan,
    failed_kill,
    successful_kill,
)
from tests.main.parser_help_helpers import flat_help, parser_for


def _args(
    provider: str = "claude",
    *,
    json_mode: bool = False,
    dry_run: bool = False,
    yes: bool = False,
    model: str | None = None,
    limit: int = 20,
) -> argparse.Namespace:
    return argparse.Namespace(
        provider=provider,
        json=json_mode,
        dry_run=dry_run,
        yes=yes,
        model=model,
        limit=limit,
    )


def _disable(provider: str = "claude") -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=2,
        provider=provider,
        created_at=1_800_000_000.0,
        expires_at=None,
        source="usage_limit",
        mode="hard",
    )


def _move(tmp_path: Path, name: str = "02p", *, status: str = "RUNNING"):
    restart_plan = dummy_plan(tmp_path / name, name=name)
    return ProviderDrainMove(
        name=name,
        presented_name=name,
        project="gh_sase-org__sase",
        status=status,
        route=DrainRoute(
            kind="reroute",
            target_provider="codex",
            target_model="gpt-5",
        ),
        restart_plan=restart_plan,
    )


def _skip(name: str = "03p") -> ProviderDrainSkip:
    return ProviderDrainSkip(
        name=name,
        presented_name=name,
        status="QUESTION",
        reason="pending_question",
        detail="holding a pending question; a restart would destroy it",
    )


def _plan(
    moves: list[ProviderDrainMove],
    *,
    skips: list[ProviderDrainSkip] | None = None,
    model_override: str | None = None,
    limit: int = 20,
) -> ProviderDrainPlan:
    return ProviderDrainPlan(
        provider="claude",
        disable=_disable(),
        moves=tuple(moves),
        skips=tuple(skips or []),
        model_override=model_override,
        limit=limit,
    )


def _ok_outcome(plan: ProviderDrainPlan) -> ProviderDrainOutcome:
    results = tuple(
        AgentRestartOutcome(
            status="ok",
            name=move.name,
            stop_action="killed",
            stop_result=successful_kill(),
            launched_pid=492011,
            launched_workspace_num=14,
            launched_artifacts_dir=f"/tmp/new-{move.name}",
        )
        for move in plan.moves
    )
    return ProviderDrainOutcome(plan=plan, results=results)


def test_parser_registers_drain_flags() -> None:
    args = create_parser().parse_args(
        [
            "agent",
            "drain",
            "claude",
            "-j",
            "-l",
            "3",
            "-m",
            "codex/gpt-5",
            "-n",
            "-y",
        ]
    )

    assert args.agent_subcommand == "drain"
    assert args.provider == "claude"
    assert args.json is True
    assert args.limit == 3
    assert args.model == "codex/gpt-5"
    assert args.dry_run is True
    assert args.yes is True


def test_parser_help_documents_examples_and_exit_codes() -> None:
    help_text = flat_help(parser_for(("sase", "agent", "drain")).format_help())
    assert "sase agent drain claude --dry-run" in help_text
    assert "--limit" in help_text
    assert "--model" in help_text
    assert "--yes" in help_text
    assert "0" in help_text
    assert "2" in help_text
    assert "1" in help_text


def test_dry_run_prints_preview_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _plan([_move(tmp_path)], skips=[_skip()])

    def fail_execute(*_args: object, **_kwargs: object) -> ProviderDrainOutcome:
        raise AssertionError("execute should not run for dry-run")

    rc = run_agents_drain(
        _args(dry_run=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=fail_execute,
    ).exit_code

    assert rc == 0
    output = capsys.readouterr().out
    assert "Drain" in output
    assert "02p" in output
    assert "pending question" in output


def test_json_dry_run_envelope_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _plan([_move(tmp_path)], skips=[_skip()])
    rc = run_agents_drain(
        _args(dry_run=True, json_mode=True),
        plan_fn=lambda *_a, **_k: plan,
    ).exit_code

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == AGENT_DRAIN_JSON_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["provider"] == "claude"
    assert payload["counts"]["moves"] == 1
    assert payload["counts"]["skipped"] == 1
    assert payload["moves"][0]["route"]["target_provider"] == "codex"
    assert payload["results"] == []
    assert payload["error"] is None


def test_model_and_limit_are_passed_to_planner(tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    plan = _plan([_move(tmp_path)], model_override="codex/gpt-5", limit=3)

    def plan_fn(provider: str, *, model_override: str | None, limit: int):
        seen.update(
            provider=provider,
            model_override=model_override,
            limit=limit,
        )
        return plan

    rc = run_agents_drain(
        _args(model="codex/gpt-5", limit=3, dry_run=True),
        plan_fn=plan_fn,
    ).exit_code

    assert rc == 0
    assert seen == {
        "provider": "claude",
        "model_override": "codex/gpt-5",
        "limit": 3,
    }


def test_declined_tty_confirmation_exits_2_and_changes_nothing(
    tmp_path: Path,
) -> None:
    plan = _plan([_move(tmp_path)])

    def fail_execute(*_args: object, **_kwargs: object) -> ProviderDrainOutcome:
        raise AssertionError("execute should not run after decline")

    rc = run_agents_drain(
        _args(),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=fail_execute,
        confirm_fn=lambda *_a, **_k: False,
        is_tty_fn=lambda: True,
    ).exit_code

    assert rc == 2


def test_non_tty_live_drain_requires_yes(tmp_path: Path) -> None:
    plan = _plan([_move(tmp_path)])

    def fail_execute(*_args: object, **_kwargs: object) -> ProviderDrainOutcome:
        raise AssertionError("execute should not run without confirmation")

    rc = run_agents_drain(
        _args(),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=fail_execute,
        is_tty_fn=lambda: False,
    ).exit_code

    assert rc == 2


def test_yes_skips_confirmation_and_executes(tmp_path: Path) -> None:
    plan = _plan([_move(tmp_path)])
    confirm_calls = {"n": 0}

    def confirm(*_args: object, **_kwargs: object) -> bool:
        confirm_calls["n"] += 1
        return False

    rc = run_agents_drain(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: _ok_outcome(plan),
        confirm_fn=confirm,
        is_tty_fn=lambda: True,
    ).exit_code

    assert rc == 0
    assert confirm_calls["n"] == 0


def test_no_moves_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plan = _plan([], skips=[_skip()])

    def fail_execute(*_args: object, **_kwargs: object) -> ProviderDrainOutcome:
        raise AssertionError("execute should not run with no moves")

    rc = run_agents_drain(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=fail_execute,
    ).exit_code

    assert rc == 2
    assert "No agents can be relaunched" in capsys.readouterr().err


def test_planning_error_json_exits_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = ProviderDrainError(
        reason="not_disabled",
        message="'claude' has no active disable; nothing to drain.",
        hint="Disable it first in Launch Control.",
    )

    def raise_error(*_args: object, **_kwargs: object) -> ProviderDrainPlan:
        raise error

    rc = run_agents_drain(
        _args(json_mode=True),
        plan_fn=raise_error,
    ).exit_code

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["reason"] == "not_disabled"
    assert payload["counts"]["moves"] == 0


def test_move_failure_exits_1_and_reports_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _plan([_move(tmp_path)], skips=[_skip()])
    outcome = ProviderDrainOutcome(
        plan=plan,
        results=(
            AgentRestartOutcome(
                status="kill_failed",
                name="02p",
                stop_action="killed",
                stop_result=failed_kill(),
                error="Permission denied",
            ),
        ),
    )

    rc = run_agents_drain(
        _args(json_mode=True, yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: outcome,
    ).exit_code

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["counts"]["failed"] == 1
    assert payload["results"][0]["status"] == "kill_failed"
    assert payload["error"]["reason"] == "move_failed"


def test_report_fn_receives_final_result_on_success(tmp_path: Path) -> None:
    plan = _plan([_move(tmp_path)])
    seen: list[Any] = []

    rc = run_agents_drain(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: _ok_outcome(plan),
        report_fn=seen.append,
    ).exit_code

    assert rc == 0
    assert len(seen) == 1
    assert seen[0] is not None
    assert seen[0].success is True


def test_report_fn_receives_result_on_planning_error() -> None:
    error = ProviderDrainError(
        reason="not_disabled", message="nope", hint="Disable it first."
    )
    seen: list[Any] = []

    def raise_error(*_a: object, **_k: object) -> ProviderDrainPlan:
        raise error

    rc = run_agents_drain(
        _args(json_mode=True),
        plan_fn=raise_error,
        report_fn=seen.append,
    ).exit_code

    assert rc == 2
    assert len(seen) == 1
    assert seen[0] is not None
    assert seen[0].success is False


def test_report_fn_receives_none_when_execution_raises_unexpectedly(
    tmp_path: Path,
) -> None:
    plan = _plan([_move(tmp_path)])
    seen: list[Any] = []

    def boom(*_a: object, **_k: object) -> ProviderDrainOutcome:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run_agents_drain(
            _args(yes=True),
            plan_fn=lambda *_a, **_k: plan,
            execute_fn=boom,
            report_fn=seen.append,
        )

    assert seen == [None]


def test_no_report_fn_is_a_no_op(tmp_path: Path) -> None:
    plan = _plan([_move(tmp_path)])

    rc = run_agents_drain(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: _ok_outcome(plan),
    ).exit_code

    assert rc == 0
