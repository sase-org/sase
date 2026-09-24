"""Tests for Codex turn-integrity enforcement on empty/unmatched final turns."""

from sase.llm_provider._subprocess import (
    CODEX_TURN_INTEGRITY_ERROR_PREFIX,
    stream_and_parse_codex_json_output,
)
from tests._llm_provider_codex_parser_helpers import (
    _load_fixture_events,
    _start_fixture_codex_process,
)


def test_codex_parser_reports_aborted_handoff_fixture() -> None:
    """The parser returns the Sep 2026 handoff evidence for provider recovery."""
    process = _start_fixture_codex_process(
        _load_fixture_events("codex-cli-aborted-empty-final.jsonl")
    )

    result = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert result.integrity_error is None
    assert len(result.stranded_commands) == 1
    command = result.stranded_commands[0]
    assert command.command_id == "exec-sudo-request"
    assert command.is_handoff is True
    assert command.reason == "killed_at_teardown"


def test_codex_parser_reports_empty_final_with_unmatched_tool_use() -> None:
    """A started non-handoff command with no result remains an integrity failure."""
    events = [
        {"type": "thread.started", "thread_id": "thread_unmatched_tool"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "cmd_still_running",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'sleep 30'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {"type": "turn.completed"},
    ]
    process = _start_fixture_codex_process(events)

    result = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert result.integrity_error is not None
    assert CODEX_TURN_INTEGRITY_ERROR_PREFIX in result.integrity_error
    assert "started without a result" in result.integrity_error
    assert "cmd_still_running" in result.integrity_error


def test_codex_parser_allows_killed_command_with_nonempty_final() -> None:
    """A non-empty final message keeps ordinary Codex turns on the success path."""
    events = [
        {"type": "thread.started", "thread_id": "thread_nonempty_final"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "cmd_interrupted",
                "type": "command_execution",
                "command": "/bin/zsh -lc 'sleep 30'",
                "aggregated_output": "",
                "exit_code": -1,
                "status": "failed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "msg_1",
                "type": "agent_message",
                "phase": "final_answer",
                "text": "The command was interrupted; reporting that result.",
            },
        },
        {"type": "turn.completed"},
    ]
    process = _start_fixture_codex_process(events)

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert (text, stderr, rc) == (
        "The command was interrupted; reporting that result.",
        "",
        0,
    )
