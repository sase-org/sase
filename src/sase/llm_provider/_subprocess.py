"""Compatibility exports for shared LLM subprocess utilities."""

import os
import select

from . import _subprocess_claude as _claude
from . import _subprocess_codex as _codex
from . import _subprocess_opencode as _opencode
from . import _subprocess_plain as _plain
from . import _subprocess_qwen as _qwen
from ._subprocess_artifacts import (
    append_stream_text,
    initial_usage_totals,
    int_usage,
    open_codex_thinking_file,
    open_live_reply_file,
    open_live_reply_timestamps_file,
    strip_ansi,
    write_usage_artifact,
)

_accumulate_opencode_usage = _opencode._accumulate_opencode_usage
_accumulate_qwen_usage = _qwen._accumulate_qwen_usage
_append_stream_text = append_stream_text
_capture_opencode_diagnostic = _opencode._capture_opencode_diagnostic
_capture_qwen_diagnostic = _qwen._capture_qwen_diagnostic
_extract_text_from_content = _qwen._extract_text_from_content
_flush_codex_reasoning = _codex._flush_codex_reasoning
_format_codex_action = _codex._format_codex_action
_initial_usage_totals = initial_usage_totals
_int_usage = int_usage
_open_codex_thinking_file = open_codex_thinking_file
_open_live_reply_file = open_live_reply_file
_open_live_reply_timestamps_file = open_live_reply_timestamps_file
_opencode_texts = _opencode._opencode_texts
_process_codex_json_line = _codex._process_codex_json_line
_process_json_line = _claude._process_json_line
_process_opencode_json_line = _opencode._process_opencode_json_line
_process_qwen_json_line = _qwen._process_qwen_json_line
_qwen_assistant_texts = _qwen._qwen_assistant_texts
_qwen_result_text = _qwen._qwen_result_text
_strip_ansi = strip_ansi
_write_codex_thinking = _codex._write_codex_thinking
_write_usage_artifact = write_usage_artifact
start_interrupt_monitor = _plain.start_interrupt_monitor
stream_and_parse_codex_json_output = _codex.stream_and_parse_codex_json_output
stream_and_parse_json_output = _claude.stream_and_parse_json_output
stream_and_parse_opencode_json_output = _opencode.stream_and_parse_opencode_json_output
stream_and_parse_qwen_json_output = _qwen.stream_and_parse_qwen_json_output
stream_process_output = _plain.stream_process_output

__all__ = [
    "_accumulate_opencode_usage",
    "_accumulate_qwen_usage",
    "_append_stream_text",
    "_capture_opencode_diagnostic",
    "_capture_qwen_diagnostic",
    "_extract_text_from_content",
    "_flush_codex_reasoning",
    "_format_codex_action",
    "_initial_usage_totals",
    "_int_usage",
    "_open_codex_thinking_file",
    "_open_live_reply_file",
    "_open_live_reply_timestamps_file",
    "_opencode_texts",
    "_process_codex_json_line",
    "_process_json_line",
    "_process_opencode_json_line",
    "_process_qwen_json_line",
    "_qwen_assistant_texts",
    "_qwen_result_text",
    "_strip_ansi",
    "_write_codex_thinking",
    "_write_usage_artifact",
    "os",
    "select",
    "start_interrupt_monitor",
    "stream_and_parse_codex_json_output",
    "stream_and_parse_json_output",
    "stream_and_parse_opencode_json_output",
    "stream_and_parse_qwen_json_output",
    "stream_process_output",
]
