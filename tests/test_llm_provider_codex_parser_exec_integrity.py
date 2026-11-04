"""Turn-integrity regressions for the phaseless codex exec stdout format."""

import pytest

from sase.llm_provider._subprocess_codex import stream_and_parse_codex_json_output
from tests._llm_provider_codex_parser_helpers import (
    _load_fixture_events,
    _start_fixture_codex_process,
)


def _command_event(event_type: str, exit_code: int | None = None) -> dict[str, object]:
    return {
        "type": event_type,
        "item": {
            "id": "cmd_sleep",
            "type": "command_execution",
            "command": "sleep 30",
            "exit_code": exit_code,
            "status": "failed" if exit_code == -1 else "in_progress",
        },
    }


def _message_event(text: str) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {"id": "msg", "type": "agent_message", "text": text},
    }


def test_codex_parser_accepts_midturn_spawn_failure_fixture() -> None:
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            _load_fixture_events("codex-cli-0.166.0-midturn-spawn-failure.jsonl")
        ),
        suppress_output=True,
    )

    assert result.integrity_error is None
    assert result.stranded_commands == ()
    assert "Implemented the change and staged verification." in result.content


@pytest.mark.parametrize(
    "next_item_type", ["command_execution", "file_change", "unknown"]
)
def test_codex_exec_commentary_before_new_work_does_not_hide_abort(
    next_item_type: str,
) -> None:
    events = [
        _message_event("I will run the next command."),
        {"type": "item.started", "item": {"id": "cmd_sleep", "type": next_item_type}},
        _command_event("item.completed", -1),
        {"type": "turn.completed"},
    ]
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(events), suppress_output=True
    )

    assert result.integrity_error is not None
    assert "killed at teardown" in result.integrity_error


def test_codex_exec_command_without_result_still_fails() -> None:
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            [_command_event("item.started"), {"type": "turn.completed"}]
        ),
        suppress_output=True,
    )

    assert result.integrity_error is not None
    assert "started without a result" in result.integrity_error


@pytest.mark.parametrize("completion_position", [0, 1, 2])
def test_codex_exec_final_survives_inflight_teardown(
    completion_position: int,
) -> None:
    """Turn completion is a flag, including when teardown events arrive after it."""
    tail = [
        _message_event("Finished; the background command was still running."),
        _command_event("item.completed", -1),
    ]
    tail.insert(completion_position, {"type": "turn.completed"})
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process([_command_event("item.started"), *tail]),
        suppress_output=True,
    )

    assert result.integrity_error is None
    assert len(result.stranded_commands) == 1
    stranded = result.stranded_commands[0]
    assert stranded.command_id == "cmd_sleep"
    assert stranded.reason == "killed_at_teardown"
    assert not stranded.is_handoff


@pytest.mark.parametrize("phase_location", ["item", "payload"])
def test_codex_explicit_commentary_cannot_be_final_candidate(
    phase_location: str,
) -> None:
    message: dict[str, object] = {
        "id": "msg",
        "type": "agent_message",
        "text": "I am still working.",
    }
    event: dict[str, object] = {"type": "item.completed", "item": message}
    if phase_location == "item":
        message["phase"] = "commentary"
    else:
        event["phase"] = "commentary"
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            [event, _command_event("item.completed", -1), {"type": "turn.completed"}]
        ),
        suppress_output=True,
    )

    assert result.integrity_error is not None
    assert "killed at teardown" in result.integrity_error


@pytest.mark.parametrize("text", ["", " \n "])
def test_codex_empty_phaseless_message_cannot_be_final_candidate(text: str) -> None:
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            [
                _message_event(text),
                _command_event("item.completed", -1),
                {"type": "turn.completed"},
            ]
        ),
        suppress_output=True,
    )

    assert result.integrity_error is not None


@pytest.mark.parametrize(
    "progress_event",
    [
        {"type": "item.started", "item": {"id": "new", "type": "file_change"}},
        _message_event("The previous command failed."),
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "phase": "commentary",
                "text": "Retrying.",
            },
        },
    ],
)
def test_codex_turn_progress_discards_midturn_kills(
    progress_event: dict[str, object],
) -> None:
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            [
                _command_event("item.completed", -1),
                progress_event,
                {"type": "turn.completed"},
            ]
        ),
        suppress_output=True,
    )

    assert result.integrity_error is None
    assert result.stranded_commands == ()


def test_codex_turn_progress_preserves_commands_without_results() -> None:
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            [
                _command_event("item.started"),
                _message_event("Still working."),
                {"type": "item.started", "item": {"type": "file_change"}},
                {"type": "turn.completed"},
            ]
        ),
        suppress_output=True,
    )

    assert result.integrity_error is not None
    assert "started without a result" in result.integrity_error
    assert len(result.stranded_commands) == 1
    assert result.stranded_commands[0].reason == "started_without_result"


@pytest.mark.parametrize("completion_type", ["turn.completed", "task_complete"])
def test_codex_task_completion_final_signal_still_allows_teardown(
    completion_type: str,
) -> None:
    result = stream_and_parse_codex_json_output(
        _start_fixture_codex_process(
            [
                {"type": completion_type, "last_agent_message": "Finished."},
                _command_event("item.completed", -1),
            ]
        ),
        suppress_output=True,
    )

    assert result.integrity_error is None
    assert len(result.stranded_commands) == 1
