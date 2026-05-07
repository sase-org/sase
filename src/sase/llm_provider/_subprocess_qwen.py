"""Qwen Code stream-json subprocess parsing."""

import json
import subprocess
from collections.abc import Mapping
from typing import IO

from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    int_usage,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_usage_artifact,
)
from ._subprocess_stream import append_error_events, stream_json_lines


def stream_and_parse_qwen_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Qwen Code ``stream-json`` events and extract assistant text."""
    assistant_texts: list[str] = []
    error_events: list[str] = []
    usage_totals = initial_usage_totals()
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_qwen_json_line(
                line,
                assistant_texts,
                suppress_output,
                error_events,
                live_reply_file,
                timestamps_file,
                usage_totals,
            ),
            suppress_output,
        )
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    combined_text = "\n\n".join(assistant_texts)
    write_usage_artifact(usage_totals)
    stderr_content = append_error_events(stderr_content, return_code, error_events)

    return combined_text, stderr_content, return_code, usage_totals


def _process_qwen_json_line(
    line: str,
    assistant_texts: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    timestamps_file: IO[str] | None = None,
    usage_totals: dict[str, int] | None = None,
) -> None:
    """Parse one Qwen Code stream-json line.

    Assistant events are streamed immediately. Result text is captured only
    when no assistant text has been seen, avoiding duplicate final answers for
    Qwen versions that emit both event types.
    """
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return

    event_type = event.get("type")

    if event_type == "assistant":
        for text in _qwen_assistant_texts(event):
            append_stream_text(
                text,
                assistant_texts,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "result":
        _capture_qwen_diagnostic(event, "result", error_events)
        if usage_totals is not None:
            _accumulate_qwen_usage(event.get("usage"), usage_totals)
        result_text = _qwen_result_text(event)
        if result_text and not assistant_texts:
            append_stream_text(
                result_text,
                assistant_texts,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "error":
        _capture_qwen_diagnostic(event, "error", error_events)


def _qwen_assistant_texts(event: Mapping[str, object]) -> list[str]:
    """Extract text blocks from known Qwen assistant event shapes."""
    texts: list[str] = []
    message = event.get("message")
    if isinstance(message, dict):
        texts.extend(_extract_text_from_content(message.get("content")))
    texts.extend(_extract_text_from_content(event.get("content")))
    return [text for text in texts if text]


def _qwen_result_text(event: Mapping[str, object]) -> str:
    """Extract final text from known Qwen result event fields."""
    for key in ("result", "response", "text", "content"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    message = event.get("message")
    if isinstance(message, dict):
        texts = _extract_text_from_content(message.get("content"))
        if texts:
            return "\n".join(texts)
    return ""


def _extract_text_from_content(content: object) -> list[str]:
    """Extract text from a string or list of content blocks."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return texts


def _capture_qwen_diagnostic(
    event: Mapping[str, object],
    event_type: str,
    error_events: list[str] | None,
) -> None:
    """Capture Qwen error/result detail for non-zero exit diagnostics."""
    if error_events is None:
        return
    detail = event.get("error") or event.get("message") or event.get("result", "")
    if isinstance(detail, dict):
        detail = detail.get("message", json.dumps(detail))
    if isinstance(detail, str) and detail:
        error_events.append(f"[{event_type}] {detail}")


def _accumulate_qwen_usage(
    usage: object,
    usage_totals: dict[str, int],
) -> None:
    """Accumulate Qwen token usage into SASE's common usage keys."""
    if not isinstance(usage, dict):
        return

    usage_totals["input_tokens"] += int_usage(
        usage.get("input_tokens", usage.get("prompt_tokens", 0))
    )
    usage_totals["output_tokens"] += int_usage(
        usage.get("output_tokens", usage.get("completion_tokens", 0))
    )
    usage_totals["cache_creation_input_tokens"] += int_usage(
        usage.get("cache_creation_input_tokens", 0)
    )
    usage_totals["cache_read_input_tokens"] += int_usage(
        usage.get("cache_read_input_tokens", 0)
    )
