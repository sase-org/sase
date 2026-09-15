"""Claude provider background-wait guard tests."""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess_claude import (
    ClaudeTurnWaitState,
    _process_json_line,
)
from sase.llm_provider.claude import (
    ClaudeCodeProvider,
    _BASH_MAX_TIMEOUT_MS,
    _WAIT_CONTINUATION_NUDGE,
    _classify_claude_wait_state,
)
from sase.llm_provider.types import LLMInvocationError


def _usage(input_tokens: int = 0, output_tokens: int = 0) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def _install_popen_processes(mock_popen: MagicMock) -> list[MagicMock]:
    processes: list[MagicMock] = []

    def _make_process(*_args: object, **_kwargs: object) -> MagicMock:
        process = MagicMock()
        process.stdin = MagicMock()
        processes.append(process)
        return process

    mock_popen.side_effect = _make_process
    return processes


@patch(
    "sase.llm_provider.claude.stream_and_parse_json_output",
    return_value=("", "", 0, _usage()),
)
@patch("sase.llm_provider.claude.subprocess.Popen")
def test_claude_run_subprocess_disables_backgrounding_by_default(
    mock_popen: MagicMock,
    _mock_stream: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_popen_processes(mock_popen)
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", raising=False)
    monkeypatch.delenv("BASH_MAX_TIMEOUT_MS", raising=False)

    ClaudeCodeProvider()._run_subprocess(["claude", "-p"], "prompt", True)

    env = mock_popen.call_args.kwargs["env"]
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert env["BASH_MAX_TIMEOUT_MS"] == _BASH_MAX_TIMEOUT_MS


@patch(
    "sase.llm_provider.claude.stream_and_parse_json_output",
    return_value=("", "", 0, _usage()),
)
@patch("sase.llm_provider.claude.subprocess.Popen")
def test_claude_run_subprocess_respects_operator_env(
    mock_popen: MagicMock,
    _mock_stream: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_popen_processes(mock_popen)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "")
    monkeypatch.setenv("BASH_MAX_TIMEOUT_MS", "123")

    ClaudeCodeProvider()._run_subprocess(["claude", "-p"], "prompt", True)

    env = mock_popen.call_args.kwargs["env"]
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == ""
    assert env["BASH_MAX_TIMEOUT_MS"] == "123"


def test_claude_wait_state_collector_tracks_background_and_wakeup() -> None:
    wait_state = ClaudeTurnWaitState()

    _process_json_line(
        json.dumps(
            {
                "type": "user",
                "tool_use_result": {"backgroundTaskId": "bg-structured"},
            }
        ),
        assistant_texts=[],
        suppress_output=True,
        wait_state=wait_state,
    )
    _process_json_line(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "Command running in background with ID: bg-text",
                        }
                    ]
                },
            }
        ),
        assistant_texts=[],
        suppress_output=True,
        wait_state=wait_state,
    )

    assert wait_state.outstanding_background_tasks == {"bg-structured", "bg-text"}

    _process_json_line(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "<task-notification><task-id>bg-text</task-id>"
                                "<status>completed</status></task-notification>"
                            ),
                        }
                    ]
                },
            }
        ),
        assistant_texts=[],
        suppress_output=True,
        wait_state=wait_state,
    )
    _process_json_line(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "ScheduleWakeup",
                            "input": {"stop": True},
                        },
                        {
                            "type": "tool_use",
                            "name": "ScheduleWakeup",
                            "input": {"seconds": 30},
                        },
                        {"type": "text", "text": "I will be notified later."},
                    ]
                },
            }
        ),
        assistant_texts=[],
        suppress_output=True,
        wait_state=wait_state,
    )

    assert wait_state.outstanding_background_tasks == {"bg-structured"}
    assert wait_state.schedule_wakeup_requested is True
    assert wait_state.final_text_tail == "I will be notified later."


@pytest.mark.parametrize(
    "tail",
    [
        "...so I'll wait.",
        "I'll be notified automatically when it completes.",
    ],
)
def test_claude_wait_state_classifier_background_wait_tails(tail: str) -> None:
    wait_state = ClaudeTurnWaitState(
        outstanding_background_tasks={"bg-1"},
        final_text_tail=tail,
    )

    assert _classify_claude_wait_state(wait_state) == (
        True,
        "background_task_wait:bg-1",
    )


def test_claude_wait_state_classifier_ignores_complete_background_answer() -> None:
    wait_state = ClaudeTurnWaitState(
        outstanding_background_tasks={"bg-1"},
        final_text_tail="Implemented the fix and verified the provider tests passed.",
    )

    assert _classify_claude_wait_state(wait_state) == (
        False,
        "background_tasks_without_wait_reply",
    )


def test_claude_wait_state_classifier_requires_structural_signal() -> None:
    wait_state = ClaudeTurnWaitState(final_text_tail="I'll wait for it to finish.")

    assert _classify_claude_wait_state(wait_state) == (False, "no_wait_state")


def test_claude_wait_state_classifier_flags_schedule_wakeup() -> None:
    wait_state = ClaudeTurnWaitState(schedule_wakeup_requested=True)

    assert _classify_claude_wait_state(wait_state) == (
        True,
        "schedule_wakeup_tool_use",
    )


@patch.dict(os.environ, {"SASE_CLAUDE_MAX_WAIT_CONTINUATIONS": "2"})
@patch("sase.llm_provider.claude.uuid.uuid4")
@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch(
    "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
    return_value=None,
)
def test_claude_provider_resumes_after_wait_state_reply(
    _mock_usage_context: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    mock_uuid4: MagicMock,
) -> None:
    processes = _install_popen_processes(mock_popen)
    mock_uuid4.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")
    calls = {"n": 0}

    def _stream_side_effect(
        _process: object,
        suppress_output: bool = False,
        *,
        usage_context: object | None = None,
        wait_state: ClaudeTurnWaitState | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output, usage_context
        calls["n"] += 1
        if calls["n"] == 1:
            assert wait_state is not None
            wait_state.outstanding_background_tasks.add("bg-1")
            wait_state.final_text_tail = "The command is still running, so I'll wait."
            return ("I started verification and will wait.", "", 0, _usage(1, 2))
        return ("Done now.", "", 0, _usage(3, 4))

    mock_stream.side_effect = _stream_side_effect

    result = ClaudeCodeProvider().invoke(
        "run verification",
        model_tier="large",
        suppress_output=True,
    )

    assert result.content == "I started verification and will wait.\n\nDone now."
    assert result.usage == _usage(4, 6)
    assert mock_popen.call_count == 2
    first_cmd = mock_popen.call_args_list[0].args[0]
    second_cmd = mock_popen.call_args_list[1].args[0]
    session_id = first_cmd[first_cmd.index("--session-id") + 1]
    assert second_cmd[second_cmd.index("--resume") + 1] == session_id
    assert "--session-id" not in second_cmd
    assert processes[0].stdin.write.call_args.args[0] == "run verification"
    assert processes[1].stdin.write.call_args.args[0] == _WAIT_CONTINUATION_NUDGE


@patch.dict(os.environ, {"SASE_CLAUDE_MAX_WAIT_CONTINUATIONS": "1"})
@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch(
    "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
    return_value=None,
)
def test_claude_provider_wait_state_cap_exhaustion_raises(
    _mock_usage_context: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    _install_popen_processes(mock_popen)

    def _stream_side_effect(
        _process: object,
        suppress_output: bool = False,
        *,
        usage_context: object | None = None,
        wait_state: ClaudeTurnWaitState | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del suppress_output, usage_context
        assert wait_state is not None
        wait_state.outstanding_background_tasks.add("bg-1")
        wait_state.final_text_tail = "I'll wait for the background task."
        return ("I'll wait for the background task.", "", 0, _usage())

    mock_stream.side_effect = _stream_side_effect

    with pytest.raises(LLMInvocationError) as exc_info:
        ClaudeCodeProvider().invoke(
            "run verification",
            model_tier="large",
            suppress_output=True,
        )

    assert mock_popen.call_count == 2
    message = str(exc_info.value)
    assert "wait-for-background reply" in message
    assert "background_task_wait:bg-1" in message


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch(
    "sase.llm_provider.usage.claude.capture_claude_passive_usage_context",
    return_value=None,
)
def test_claude_provider_clean_answer_does_not_continue(
    _mock_usage_context: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    _install_popen_processes(mock_popen)
    mock_stream.return_value = ("All done.", "", 0, _usage(5, 6))

    result = ClaudeCodeProvider().invoke(
        "fix it",
        model_tier="small",
        suppress_output=True,
    )

    assert mock_popen.call_count == 1
    assert result.content == "All done."
    assert result.usage == _usage(5, 6)


def test_claude_provider_interrupt_restart_uses_fresh_session() -> None:
    provider = ClaudeCodeProvider()
    calls = {"n": 0}

    def _fake_run(
        args: list[str],
        prompt: str,
        suppress_output: bool,
        *,
        wait_state: ClaudeTurnWaitState | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        del prompt, suppress_output, wait_state
        calls["n"] += 1
        if calls["n"] == 1:
            provider._pending_interrupt_message = "new user input"
            return ("partial", "", 130, _usage())
        return ("finished", "", 0, _usage())

    with patch.object(provider, "_run_subprocess", side_effect=_fake_run) as mock_run:
        result = provider.invoke("start", model_tier="large", suppress_output=True)

    assert result.content == "partial\n\nfinished"
    assert mock_run.call_count == 2
    first_cmd = mock_run.call_args_list[0].args[0]
    second_cmd = mock_run.call_args_list[1].args[0]
    first_session = first_cmd[first_cmd.index("--session-id") + 1]
    second_session = second_cmd[second_cmd.index("--session-id") + 1]
    assert first_session != second_session
    assert "--resume" not in second_cmd
