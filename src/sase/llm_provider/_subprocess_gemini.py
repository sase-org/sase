"""Gemini CLI stream-json subprocess parsing."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from typing import IO, Any

from ._subprocess_artifacts import (
    initial_usage_totals,
    int_usage,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    write_reply_timestamp,
    write_usage_artifact,
)
from ._subprocess_stream import append_error_events, stream_json_lines
from ._tool_calls import append_gemini_tool_call_event


def stream_and_parse_gemini_json_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
) -> tuple[str, str, int, dict[str, int]]:
    """Stream Gemini CLI ``stream-json`` events and extract assistant text."""
    assistant_chunks: list[str] = []
    error_events: list[str] = []
    usage_totals = initial_usage_totals()
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()

    try:
        stderr_content, return_code = stream_json_lines(
            process,
            lambda line: _process_gemini_json_line(
                line,
                assistant_chunks,
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

    combined_text = "".join(assistant_chunks)
    write_usage_artifact(usage_totals)
    stderr_content = append_error_events(stderr_content, return_code, error_events)

    return combined_text, stderr_content, return_code, usage_totals


def _process_gemini_json_line(
    line: str,
    assistant_chunks: list[str],
    suppress_output: bool,
    error_events: list[str] | None = None,
    live_reply_file: IO[str] | None = None,
    timestamps_file: IO[str] | None = None,
    usage_totals: dict[str, int] | None = None,
) -> None:
    """Parse one Gemini CLI stream-json line."""
    line = line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, Mapping):
        return

    event_type = event.get("type")
    append_gemini_tool_call_event(event)

    if event_type == "message":
        for text in _gemini_message_texts(event):
            _append_gemini_text(
                text,
                assistant_chunks,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "result":
        _capture_gemini_diagnostic(event, "result", error_events)
        if usage_totals is not None:
            _accumulate_gemini_usage(event, usage_totals)
        result_text = _gemini_result_text(event)
        if result_text and not assistant_chunks:
            _append_gemini_text(
                result_text,
                assistant_chunks,
                suppress_output,
                live_reply_file,
                timestamps_file,
            )
    elif event_type == "error":
        _capture_gemini_diagnostic(event, "error", error_events)


def _append_gemini_text(
    text: str,
    assistant_chunks: list[str],
    suppress_output: bool,
    live_reply_file: IO[str] | None,
    timestamps_file: IO[str] | None,
) -> None:
    """Append a Gemini message chunk without forcing paragraph boundaries."""
    if not text:
        return
    if live_reply_file:
        if not assistant_chunks:
            write_reply_timestamp(live_reply_file, timestamps_file)
        live_reply_file.write(text)
        live_reply_file.flush()
    assistant_chunks.append(text)
    if not suppress_output:
        print(text, end="", file=sys.stdout, flush=True)


def _gemini_message_texts(event: Mapping[str, Any]) -> list[str]:
    """Extract assistant text chunks from known Gemini message event shapes."""
    role = event.get("role")
    if isinstance(role, str) and role not in {"assistant", "model"}:
        return []

    texts: list[str] = []
    message = event.get("message")
    if isinstance(message, Mapping):
        message_role = message.get("role")
        if isinstance(message_role, str) and message_role not in {"assistant", "model"}:
            return []
        texts.extend(_extract_text_from_content(message.get("content")))
        texts.extend(_extract_text_from_content(message.get("text")))

    for key in ("content", "text", "delta"):
        texts.extend(_extract_text_from_content(event.get(key)))
    return [text for text in texts if text]


def _gemini_result_text(event: Mapping[str, Any]) -> str:
    """Extract final text from known Gemini result event fields."""
    for key in ("response", "result", "text", "content"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    message = event.get("message")
    if isinstance(message, Mapping):
        texts = _extract_text_from_content(message.get("content"))
        if texts:
            return "".join(texts)
    return ""


def _extract_text_from_content(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for block in content:
        if isinstance(block, str):
            texts.append(block)
        elif isinstance(block, Mapping):
            block_type = block.get("type")
            if block_type in {None, "text"}:
                text = block.get("text") or block.get("content")
                if isinstance(text, str) and text:
                    texts.append(text)
    return texts


def _capture_gemini_diagnostic(
    event: Mapping[str, Any],
    event_type: str,
    error_events: list[str] | None,
) -> None:
    """Capture Gemini error/result detail for non-zero exit diagnostics."""
    if error_events is None:
        return
    detail = event.get("error") or event.get("message") or event.get("result", "")
    if isinstance(detail, Mapping):
        detail = detail.get("message", json.dumps(detail))
    if isinstance(detail, str) and detail:
        error_events.append(f"[{event_type}] {detail}")


def _accumulate_gemini_usage(
    event: Mapping[str, Any],
    usage_totals: dict[str, int],
) -> None:
    """Accumulate Gemini token usage into SASE's common usage keys."""
    stats = event.get("stats")
    usage = event.get("usage")
    for candidate in (usage, stats):
        if isinstance(candidate, Mapping):
            _accumulate_gemini_usage_mapping(candidate, usage_totals)

    if isinstance(stats, Mapping):
        models = stats.get("models") or stats.get("per_model") or stats.get("perModel")
        if isinstance(models, Mapping):
            for model_usage in models.values():
                if isinstance(model_usage, Mapping):
                    _accumulate_gemini_usage_mapping(model_usage, usage_totals)
        elif isinstance(models, list):
            for model_usage in models:
                if isinstance(model_usage, Mapping):
                    _accumulate_gemini_usage_mapping(model_usage, usage_totals)


def _accumulate_gemini_usage_mapping(
    usage: Mapping[str, Any],
    usage_totals: dict[str, int],
) -> None:
    usage_totals["input_tokens"] += int_usage(
        usage.get(
            "input_tokens",
            usage.get("prompt_tokens", usage.get("totalInputTokens", 0)),
        )
    )
    usage_totals["output_tokens"] += int_usage(
        usage.get(
            "output_tokens",
            usage.get("completion_tokens", usage.get("totalOutputTokens", 0)),
        )
    )
    usage_totals["cache_creation_input_tokens"] += int_usage(
        usage.get("cache_creation_input_tokens", 0)
    )
    usage_totals["cache_read_input_tokens"] += int_usage(
        usage.get("cache_read_input_tokens", usage.get("cachedContentTokenCount", 0))
    )


process_gemini_json_line = _process_gemini_json_line
