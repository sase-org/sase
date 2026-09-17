"""Tests for Codex turn-integrity enforcement on empty/unmatched final turns."""

import pytest

from sase.llm_provider._subprocess import (
    CODEX_TURN_INTEGRITY_ERROR_PREFIX,
    stream_and_parse_codex_json_output,
)
from sase.llm_provider.types import LLMInvocationError

from tests._llm_provider_codex_parser_helpers import (
    _load_fixture_events,
    _start_fixture_codex_process,
)


def test_codex_parser_raises_on_aborted_empty_final_fixture() -> None:
    """The Sep 2026 empty-final/killed-command shape is provider failure."""
    process = _start_fixture_codex_process(
        _load_fixture_events("codex-cli-aborted-empty-final.jsonl")
    )

    with pytest.raises(LLMInvocationError) as exc_info:
        stream_and_parse_codex_json_output(process, suppress_output=True)

    message = str(exc_info.value)
    assert CODEX_TURN_INTEGRITY_ERROR_PREFIX in message
    assert "no final agent message" in message
    assert "exit_code -1" in message
    assert "exec-sudo-request" in message


def test_codex_parser_raises_on_empty_final_with_unmatched_tool_use() -> None:
    """A started command with no result is the same turn-integrity failure."""
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

    with pytest.raises(LLMInvocationError) as exc_info:
        stream_and_parse_codex_json_output(process, suppress_output=True)

    assert CODEX_TURN_INTEGRITY_ERROR_PREFIX in str(exc_info.value)
    assert "started without a result" in str(exc_info.value)
    assert "cmd_still_running" in str(exc_info.value)


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
