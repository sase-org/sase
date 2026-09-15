"""Claude Code stream-json subprocess parsing."""

import json
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, IO

from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    open_codex_thinking_file,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_usage_artifact,
)
from ._subprocess_diagnostics import record_stdout_json_decode_diagnostic
from ._subprocess_stream import append_error_events, stream_json_lines
from ._tool_calls import append_claude_tool_call_event
from .usage.types import UsageProbeContext

ToolCallWriter = Callable[[Mapping[str, Any]], None]
ThinkingSink = Callable[[Mapping[str, Any], Mapping[str, Any], IO[str]], None]
ThinkingSinkOption = ThinkingSink | bool | None

_BACKGROUND_TASK_ID_TEXT_RE = re.compile(
    r"(?:moved to the background\s*\(ID:\s*|"
    r"backgrounded by user with ID:\s*|"
    r"running in background with ID:\s*)"
    r"(?P<task_id>[A-Za-z0-9_.:-]+)\)?",
    re.IGNORECASE,
)
_TASK_NOTIFICATION_BLOCK_RE = re.compile(
    r"<task-notification\b[^>]*>.*?</task-notification>",
    re.IGNORECASE | re.DOTALL,
)
_TASK_ID_RE = re.compile(
    r"<task-id>\s*(?P<task_id>.*?)\s*</task-id>",
    re.IGNORECASE | re.DOTALL,
)
_TASK_STATUS_RE = re.compile(
    r"<status>\s*(?P<status>.*?)\s*</status>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ClaudeTurnWaitState:
    """Signals that a Claude print-mode turn may have ended while waiting."""

    outstanding_background_tasks: set[str] = field(default_factory=set)
    schedule_wakeup_requested: bool = False
    final_text_tail: str = ""


def stream_and_parse_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    *,
    usage_context: UsageProbeContext | None = None,
    wait_state: ClaudeTurnWaitState | None = None,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream stdout as JSON events and extract assistant text.

    Reads ``--output-format stream-json`` output from Claude Code, extracting
    text content from ``assistant`` events so that the full conversation is
    captured even when stop hooks inject extra turns.
    """
    return _stream_and_parse_messages_json_output(
        process,
        suppress_output=suppress_output,
        usage_context=usage_context,
        wait_state=wait_state,
    )


def stream_and_parse_messages_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    *,
    runtime: str = "claude",
    tool_call_writer: ToolCallWriter = append_claude_tool_call_event,
    thinking_sink: ThinkingSinkOption = None,
    usage_context: UsageProbeContext | None = None,
    wait_state: ClaudeTurnWaitState | None = None,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Anthropic Messages JSON events for Claude-compatible CLIs."""
    return _stream_and_parse_messages_json_output(
        process,
        suppress_output=suppress_output,
        runtime=runtime,
        tool_call_writer=tool_call_writer,
        thinking_sink=thinking_sink,
        usage_context=usage_context,
        wait_state=wait_state,
    )


def _stream_and_parse_messages_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    *,
    runtime: str = "claude",
    tool_call_writer: ToolCallWriter = append_claude_tool_call_event,
    thinking_sink: ThinkingSinkOption = None,
    usage_context: UsageProbeContext | None = None,
    wait_state: ClaudeTurnWaitState | None = None,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Anthropic Messages JSON events and extract assistant text."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    usage_totals = initial_usage_totals()
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()
    resolved_thinking_sink = _resolve_thinking_sink(thinking_sink)
    thinking_file = (
        open_codex_thinking_file() if resolved_thinking_sink is not None else None
    )

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_json_line(
                line,
                assistant_texts,
                suppress_output,
                error_events,
                live_reply_file,
                timestamps_file,
                usage_totals,
                runtime=runtime,
                tool_call_writer=tool_call_writer,
                thinking_sink=resolved_thinking_sink,
                thinking_file=thinking_file,
                usage_context=usage_context,
                wait_state=wait_state,
            ),
            suppress_output,
        )
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()
        if thinking_file:
            thinking_file.close()
        if runtime == "claude" and usage_context is not None:
            from .usage.claude import flush_claude_passive_usage_events

            flush_claude_passive_usage_events()

    combined_text = "\n\n".join(assistant_texts)
    write_usage_artifact(usage_totals)
    stderr_content = append_error_events(stderr_content, return_code, error_events)

    return combined_text, stderr_content, return_code, usage_totals


def _process_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    timestamps_file: IO[str] | None = None,
    usage_totals: dict[str, int] | None = None,
    *,
    runtime: str = "claude",
    tool_call_writer: ToolCallWriter = append_claude_tool_call_event,
    thinking_sink: ThinkingSinkOption = None,
    thinking_file: IO[str] | None = None,
    usage_context: UsageProbeContext | None = None,
    wait_state: ClaudeTurnWaitState | None = None,
) -> None:
    """Parse a single JSON line and extract assistant text if present.

    Also captures ``error`` and ``result`` events into *error_events* when
    provided so callers have diagnostic context when the process fails.

    When *usage_totals* is provided, accumulates token usage from ``result``
    events into the dict.
    """
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        record_stdout_json_decode_diagnostic(runtime, line, exc)
        return
    if not isinstance(event, Mapping):
        return

    event_type = event.get("type")
    if event_type == "rate_limit_event" and runtime == "claude":
        from .usage.claude import submit_claude_passive_usage_event

        submit_claude_passive_usage_event(event, usage_context)
    tool_call_writer(event)
    if wait_state is not None:
        _record_wait_state(event, wait_state)
    resolved_thinking_sink = _resolve_thinking_sink(thinking_sink)

    if event_type == "assistant":
        message = event.get("message", {})
        content_blocks = message.get("content", [])
        for block in content_blocks:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text":
                append_stream_text(
                    block["text"],
                    assistant_texts,
                    suppress_output,
                    live_reply_file,
                    timestamps_file,
                )
            elif (
                block.get("type") == "thinking"
                and resolved_thinking_sink is not None
                and thinking_file is not None
                and isinstance(message, Mapping)
            ):
                resolved_thinking_sink(block, message, thinking_file)
    elif event_type in ("error", "result"):
        if error_events is not None:
            detail = _messages_error_detail(event)
            if detail:
                error_events.append(f"[{event_type}] {detail}")
        if event_type == "result" and usage_totals is not None:
            usage = event.get("usage")
            if isinstance(usage, dict):
                for key in usage_totals:
                    usage_totals[key] += usage.get(key, 0)


def _record_wait_state(
    event: Mapping[str, Any],
    wait_state: ClaudeTurnWaitState,
) -> None:
    event_type = event.get("type")
    if event_type == "assistant":
        _record_assistant_wait_state(event, wait_state)
    elif event_type == "user":
        _record_user_wait_state(event, wait_state)


def _record_assistant_wait_state(
    event: Mapping[str, Any],
    wait_state: ClaudeTurnWaitState,
) -> None:
    message = event.get("message", {})
    if not isinstance(message, Mapping):
        return
    content_blocks = message.get("content", [])
    if not isinstance(content_blocks, list):
        return

    for block in content_blocks:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                wait_state.final_text_tail = text.strip()[-700:]
        elif block_type == "tool_use" and block.get("name") == "ScheduleWakeup":
            tool_input = block.get("input")
            stop = tool_input.get("stop") if isinstance(tool_input, Mapping) else None
            if stop is not True:
                wait_state.schedule_wakeup_requested = True


def _record_user_wait_state(
    event: Mapping[str, Any],
    wait_state: ClaudeTurnWaitState,
) -> None:
    tool_use_result = event.get("tool_use_result")
    if isinstance(tool_use_result, Mapping):
        task_id = tool_use_result.get("backgroundTaskId")
        if task_id:
            wait_state.outstanding_background_tasks.add(str(task_id))

    for text in _event_text_fragments(event):
        _record_background_task_ids_from_text(text, wait_state)
        _resolve_task_notifications_from_text(text, wait_state)


def _event_text_fragments(event: Mapping[str, Any]) -> list[str]:
    fragments: list[str] = []
    message = event.get("message")
    if not isinstance(message, Mapping):
        return fragments
    content = message.get("content")
    if isinstance(content, str):
        fragments.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, Mapping):
                continue
            text = block.get("text")
            if isinstance(text, str):
                fragments.append(text)
            block_content = block.get("content")
            if isinstance(block_content, str):
                fragments.append(block_content)
            elif isinstance(block_content, list):
                fragments.extend(
                    item for item in block_content if isinstance(item, str)
                )
    return fragments


def _record_background_task_ids_from_text(
    text: str,
    wait_state: ClaudeTurnWaitState,
) -> None:
    for match in _BACKGROUND_TASK_ID_TEXT_RE.finditer(text):
        task_id = match.group("task_id").strip()
        if task_id:
            wait_state.outstanding_background_tasks.add(task_id)


def _resolve_task_notifications_from_text(
    text: str,
    wait_state: ClaudeTurnWaitState,
) -> None:
    for block in _TASK_NOTIFICATION_BLOCK_RE.finditer(text):
        notification = block.group(0)
        task_match = _TASK_ID_RE.search(notification)
        status_match = _TASK_STATUS_RE.search(notification)
        if not task_match or not status_match:
            continue
        task_id = task_match.group("task_id").strip()
        status = status_match.group("status").strip()
        if task_id and status:
            wait_state.outstanding_background_tasks.discard(task_id)


def _messages_error_detail(event: Mapping[str, Any]) -> str:
    detail = event.get("error") or event.get("message") or event.get("result", "")
    if not detail:
        errors = event.get("errors")
        if isinstance(errors, list):
            return "\n".join(str(item) for item in errors if item)
    if isinstance(detail, Mapping):
        message = detail.get("message")
        if message:
            return str(message)
        return json.dumps(detail)
    if isinstance(detail, str):
        return detail
    return str(detail)


def _resolve_thinking_sink(thinking_sink: ThinkingSinkOption) -> ThinkingSink | None:
    if thinking_sink is True:
        return _write_messages_thinking
    if thinking_sink is False:
        return None
    return thinking_sink


def _write_messages_thinking(
    block: Mapping[str, Any],
    message: Mapping[str, Any],
    thinking_file: IO[str],
) -> None:
    text = block.get("thinking", "")
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        if not block.get("signature"):
            return
        usage = message.get("usage", {})
        output_tokens = (
            usage.get("output_tokens") if isinstance(usage, Mapping) else None
        )
        if isinstance(output_tokens, int) and output_tokens > 0:
            text = f"[encrypted thought · ~{output_tokens} output tokens]"
        else:
            text = "[encrypted thought]"
    entry = {
        "text": text,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
    thinking_file.write(json.dumps(entry) + "\n")
    thinking_file.flush()
