"""Surface behavior for ``sase agent restart``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.restart import AgentRestartError, AgentRestartOutcome
from sase.agent.running import RunningAgentInfo
from sase.agents._restart_render import AGENT_RESTART_JSON_SCHEMA_VERSION
from sase.agents.cli_restart import handle_agents_restart
from sase.main.parser import create_parser
from tests._agent_restart_helpers import (
    dummy_plan,
    failed_kill,
    make_restartable_agent,
    successful_kill,
)
from tests.main.parser_help_helpers import flat_help, parser_for


def _args(
    name: str = "02p",
    *,
    json_mode: bool = False,
    dry_run: bool = False,
    yes: bool = False,
    model: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        name=name,
        json=json_mode,
        dry_run=dry_run,
        yes=yes,
        model=model,
    )


def _running(name: str) -> RunningAgentInfo:
    return RunningAgentInfo(
        name=name,
        project="sase",
        pid=1,
        model="opus",
        provider="claude",
        workspace_num=1,
        duration="1s",
        approve=False,
    )


def _ok_outcome() -> AgentRestartOutcome:
    return AgentRestartOutcome(
        status="ok",
        name="02p",
        stop_action="killed",
        stop_result=successful_kill(),
        launched_pid=492011,
        launched_workspace_num=14,
        launched_artifacts_dir="/tmp/new-02p",
    )


def test_parser_registers_restart_flags() -> None:
    args = create_parser().parse_args(
        ["agent", "restart", "02p", "-j", "-n", "-y", "-m", "opus@high"]
    )
    assert args.agent_subcommand == "restart"
    assert args.name == "02p"
    assert args.json is True
    assert args.dry_run is True
    assert args.yes is True
    assert args.model == "opus@high"


def test_parser_help_documents_examples_and_exit_codes() -> None:
    help_text = flat_help(parser_for(("sase", "agent", "restart")).format_help())
    assert "sase agent restart 02p" in help_text
    assert "--dry-run" in help_text
    assert "--yes" in help_text
    assert "0" in help_text
    assert "2" in help_text
    assert "1" in help_text


def test_dry_run_prints_preview_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    with patch("sase.agents.cli_restart.execute_agent_restart") as execute_fn:
        rc = handle_agents_restart(_args(dry_run=True), plan_fn=lambda *_a, **_k: plan)
    assert rc == 0
    execute_fn.assert_not_called()
    output = capsys.readouterr().out
    assert "Restart" in output
    assert "02p" in output


def test_json_dry_run_envelope_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    rc = handle_agents_restart(
        _args(dry_run=True, json_mode=True),
        plan_fn=lambda *_a, **_k: plan,
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == AGENT_RESTART_JSON_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["name"] == "02p"
    assert payload["project"] == "gh_sase-org__sase"
    assert payload["project_display"] == "sase"
    assert payload["prompt"]["source"] == "raw_xprompt.md"
    assert payload["prompt"]["name_reuse"] == "forced"
    assert payload["stopped"] is None
    assert payload["launched"] is None
    assert payload["error"] is None
    assert isinstance(payload["warnings"], list)


def test_declined_tty_confirmation_exits_2_and_changes_nothing(
    tmp_path: Path,
) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    with patch("sase.agents.cli_restart.execute_agent_restart") as execute_fn:
        rc = handle_agents_restart(
            _args(),
            plan_fn=lambda *_a, **_k: plan,
            confirm_fn=lambda *_a, **_k: False,
            is_tty_fn=lambda: True,
        )
    assert rc == 2
    execute_fn.assert_not_called()


def test_yes_skips_confirmation(tmp_path: Path) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    confirm_calls = {"n": 0}

    def confirm(*_args: object, **_kwargs: object) -> bool:
        confirm_calls["n"] += 1
        return False

    rc = handle_agents_restart(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: _ok_outcome(),
        confirm_fn=confirm,
        is_tty_fn=lambda: True,
    )
    assert rc == 0
    assert confirm_calls["n"] == 0


def test_non_tty_does_not_prompt(tmp_path: Path) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    confirm_calls = {"n": 0}

    def confirm(*_args: object, **_kwargs: object) -> bool:
        confirm_calls["n"] += 1
        return False

    rc = handle_agents_restart(
        _args(),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: _ok_outcome(),
        confirm_fn=confirm,
        is_tty_fn=lambda: False,
    )
    assert rc == 0
    assert confirm_calls["n"] == 0


def test_not_found_exits_2_and_lists_near_misses(
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = AgentRestartError(
        reason="not_found",
        message="No agent found with name '02q'.",
        hint="List agents with `sase agent list -a`.",
    )

    def raise_missing(*_args: object, **_kwargs: object) -> None:
        raise error

    with patch(
        "sase.agent.running.list_running_agents",
        return_value=[_running("02p"), _running("03r")],
    ):
        rc = handle_agents_restart(_args("02q"), plan_fn=raise_missing)
    assert rc == 2
    stderr = capsys.readouterr().err
    assert "02q" in stderr
    assert "02p" in stderr
    assert "sase agent list -a" in stderr


def test_partial_failure_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts = make_restartable_agent(tmp_path)
    plan = dummy_plan(artifacts)
    outcome = AgentRestartOutcome(
        status="partial",
        name="02p",
        stop_action="killed",
        stop_result=successful_kill(),
        error="spawn failed",
        recovery_command=f'sase run "$(cat {artifacts}/raw_xprompt.md)"',
    )
    rc = handle_agents_restart(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: outcome,
        is_tty_fn=lambda: True,
    )
    assert rc == 1
    stderr = capsys.readouterr().err
    assert "spawn failed" in stderr
    assert "released" in stderr.lower()
    assert "sase run" in stderr


def test_json_success_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    rc = handle_agents_restart(
        _args(json_mode=True, yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: _ok_outcome(),
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == AGENT_RESTART_JSON_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["stopped"]["action"] == "killed"
    assert payload["stopped"]["pid"] == 481920
    assert payload["launched"]["pid"] == 492011
    assert payload["launched"]["workspace_num"] == 14
    assert payload["error"] is None


def test_kill_failure_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = dummy_plan(make_restartable_agent(tmp_path))
    outcome = AgentRestartOutcome(
        status="kill_failed",
        name="02p",
        stop_action="killed",
        stop_result=failed_kill(),
        error=failed_kill().message,
    )
    rc = handle_agents_restart(
        _args(yes=True),
        plan_fn=lambda *_a, **_k: plan,
        execute_fn=lambda *_a, **_k: outcome,
    )
    assert rc == 2
    stderr = capsys.readouterr().err
    assert "Permission denied" in stderr
    assert "Nothing was changed" in stderr
