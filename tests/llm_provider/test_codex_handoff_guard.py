"""Codex recovery for handoff commands stranded at turn teardown."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_plan_staged_record,
    read_staged_handoff,
    write_staged_handoff,
)
from sase.llm_provider._subprocess_codex import (
    CodexStreamResult,
    CodexStrandedCommand,
    _is_sase_handoff_command,
    stream_and_parse_codex_json_output,
)
from sase.llm_provider.codex import CodexProvider, single_turn_directive
from sase.llm_provider.types import LLMInvocationError
from tests._llm_provider_codex_parser_helpers import (
    _load_fixture_events,
    _start_fixture_codex_process,
)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "codex-cli-stranded-monitor-pending.jsonl",
        "codex-cli-stranded-monitor-killed.jsonl",
    ],
)
def test_codex_parser_reports_stranded_monitor_despite_commentary(
    fixture_name: str,
) -> None:
    """Commentary must not suppress recovery for a killed handoff command."""
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(_load_fixture_events(fixture_name)),
        suppress_output=True,
    )

    assert result.integrity_error is None
    assert len(result.stranded_commands) == 1
    command = result.stranded_commands[0]
    assert command.command_id == "exec-monitor-start"
    assert command.is_handoff is True
    assert command.reason in {"started_without_result", "killed_at_teardown"}


@pytest.mark.parametrize(
    "command",
    [
        "sase monitor start --profile verify -- just check",
        "sase plan propose plan.md",
        "sase pipe 'continue the task'",
        "sase questions '[]'",
        "sase gate create --shell < request.json",
        "sase sudo request < request.json",
        "sase launch request --prompt 'continue the task'",
        "sase run '#fork:agent continue the task'",
        "/bin/zsh -lc 'sase monitor start --profile verify -- just check'",
    ],
)
def test_sase_handoff_command_classifier_covers_staging_commands(command: str) -> None:
    assert _is_sase_handoff_command(command)


def test_codex_handoff_guard_redrives_command_and_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stranded monitor gets one reconstructed continuation with its command."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    stranded = CodexStrandedCommand(
        command_id="exec-monitor-start",
        command="sase monitor start --profile verify -- just check",
        reason="started_without_result",
        is_handoff=True,
    )
    first = CodexStreamResult("", "", 0, stranded_commands=(stranded,))
    second = CodexStreamResult("Monitor handoff completed.", "", 0)
    provider = CodexProvider()

    with patch.object(provider, "_run_subprocess", side_effect=[first, second]) as run:
        result = provider.invoke(
            "Complete the assigned bead.", model_tier="large", suppress_output=True
        )

    assert result.content == "Monitor handoff completed."
    continuation = run.call_args_list[1].args[1]
    assert "--- Work So Far ---" in continuation
    assert "--- Required Continuation ---" in continuation
    assert stranded.command in continuation
    assert "write_stdin" in continuation
    assert "No durable staged handoff was found" in continuation
    assert "/sase_final" in continuation
    assert "no monitor or handoff took effect" not in continuation
    log_entries = [
        json.loads(line)
        for line in (tmp_path / "wait_guard_log.jsonl").read_text().splitlines()
    ]
    assert len(log_entries) == 1
    assert log_entries[0]["reason"] == "stranded_handoff_command"
    assert log_entries[0]["cycle"] == 1


@pytest.mark.parametrize("budget", [0, 2])
def test_codex_handoff_guard_leaves_valid_stage_for_host_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, budget: int
) -> None:
    """A persisted stage wins over missing CLI output, even without retry budget."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_CODEX_MAX_WAIT_CONTINUATIONS", str(budget))
    record = build_plan_staged_record(
        plan_file=str(tmp_path / "plan.md"),
        original_file=str(tmp_path / "scratch.md"),
        dirty_obligations_at_stage=[],
    )
    write_staged_handoff(record, artifacts_dir=str(tmp_path))
    stranded = CodexStrandedCommand(
        command_id="exec-plan-propose",
        command="sase plan propose plan.md",
        reason="killed_at_teardown",
        is_handoff=True,
    )
    provider = CodexProvider()
    with patch.object(
        provider,
        "_run_subprocess",
        return_value=CodexStreamResult(
            "Plan staged.", "", 0, stranded_commands=(stranded,)
        ),
    ) as run:
        result = provider.invoke(
            "Plan the task.", model_tier="large", suppress_output=True
        )

    run.assert_called_once()
    assert result.content == "Plan staged."
    assert read_staged_handoff(str(tmp_path)) == record
    assert not (tmp_path / "wait_guard_log.jsonl").exists()


def test_codex_handoff_guard_refuses_retry_with_malformed_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    path = tmp_path / STAGED_HANDOFF_FILENAME
    path.write_text("{", encoding="utf-8")
    stranded = CodexStrandedCommand(
        command_id="exec-plan-propose",
        command="sase plan propose plan.md",
        reason="started_without_result",
        is_handoff=True,
    )
    provider = CodexProvider()
    with (
        patch.object(
            provider,
            "_run_subprocess",
            return_value=CodexStreamResult("", "", 0, stranded_commands=(stranded,)),
        ) as run,
        pytest.raises(LLMInvocationError, match="unreadable staged state"),
    ):
        provider.invoke("Plan the task.", model_tier="large", suppress_output=True)
    run.assert_called_once()
    assert path.read_text(encoding="utf-8") == "{"


def test_codex_completed_staging_command_needs_no_continuation() -> None:
    provider = CodexProvider()
    with patch.object(
        provider,
        "_run_subprocess",
        return_value=CodexStreamResult("Staged; declaration submitted.", "", 0),
    ) as run:
        result = provider.invoke(
            "Plan the task.", model_tier="large", suppress_output=True
        )
    run.assert_called_once()
    assert result.content == "Staged; declaration submitted."


def test_codex_retried_monitor_spawn_failure_needs_no_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A successful in-turn retry must not trigger stranded-handoff recovery."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    command = "sase monitor start --profile verify -- just check"
    events: list[dict[str, object]] = []
    for command_id, exit_code in [("failed_spawn", -1), ("retry", 0)]:
        item = {"id": command_id, "type": "command_execution", "command": command}
        events.extend(
            [
                {"type": "item.started", "item": {**item, "status": "in_progress"}},
                {
                    "type": "item.completed",
                    "item": {
                        **item,
                        "exit_code": exit_code,
                        "status": "failed" if exit_code == -1 else "completed",
                    },
                },
            ]
        )
    events.extend(
        [
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Verification staged."},
            },
            {"type": "turn.completed"},
        ]
    )
    parsed = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(events), suppress_output=True
    )
    assert parsed.integrity_error is None
    assert parsed.stranded_commands == ()

    provider = CodexProvider()
    with patch.object(provider, "_run_subprocess", return_value=parsed) as run:
        result = provider.invoke(
            "Verify the changes.", model_tier="large", suppress_output=True
        )

    run.assert_called_once()
    assert result.content == "Verification staged."
    assert not (tmp_path / "wait_guard_log.jsonl").exists()


@pytest.mark.parametrize("budget", [0, 2])
def test_codex_handoff_guard_exhaustion_names_command_and_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, budget: int
) -> None:
    """Exhausting the retry budget refuses to report an unfinished CLI as success."""
    monkeypatch.setenv("SASE_CODEX_MAX_WAIT_CONTINUATIONS", str(budget))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    stranded = CodexStrandedCommand(
        command_id="exec-monitor-start",
        command="sase monitor start --profile verify -- just check",
        reason="killed_at_teardown",
        is_handoff=True,
    )
    provider = CodexProvider()

    with (
        patch.object(
            provider,
            "_run_subprocess",
            return_value=CodexStreamResult("", "", 0, stranded_commands=(stranded,)),
        ) as run,
        pytest.raises(LLMInvocationError) as exc_info,
    ):
        provider.invoke(
            "Complete the assigned bead.", model_tier="large", suppress_output=True
        )

    message = str(exc_info.value)
    assert "stranded_handoff_command" in message
    assert stranded.command in message
    assert str(tmp_path) in message
    assert run.call_count == budget + 1


def test_stranded_non_handoff_with_nonempty_final_is_unaffected() -> None:
    """Only handoff commands force a continuation after a final answer exists."""
    non_handoff = CodexStrandedCommand(
        command_id="exec-sleep",
        command="sleep 30",
        reason="killed_at_teardown",
        is_handoff=False,
    )
    provider = CodexProvider()

    with patch.object(
        provider,
        "_run_subprocess",
        return_value=CodexStreamResult(
            "The command was interrupted; reporting that result.",
            "",
            0,
            stranded_commands=(non_handoff,),
        ),
    ):
        result = provider.invoke(
            "Complete the assigned bead.", model_tier="large", suppress_output=True
        )

    assert result.content == "The command was interrupted; reporting that result."


def test_codex_single_turn_directive_states_unified_exec_ceiling() -> None:
    directive = single_turn_directive()

    assert "yield_time_ms" in directive
    assert "still running" in directive
    assert "write_stdin" in directive
    assert "up to a minute" in directive
    assert "Staged" in directive
    assert "/sase_final" in directive
    assert "after this turn ends and finalizers settle" in directive
