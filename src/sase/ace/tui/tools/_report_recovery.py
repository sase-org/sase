"""Transcript recovery for slow tool-call reports."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.llm_provider._tool_call_common import (
    COMMAND_OUTPUT_MIN_TAIL_LINES,
    command_output_omission_marker,
    command_output_tail_start,
)

from ._entry import ToolCallEntry

DEFAULT_MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_RECOVERED_OUTPUT_CHARS = 64 * 1024
_RECOVERED_OUTPUT_SEPARATOR = "\n\n---\n\n"
_TEXT_RESULT_KEYS = (
    "stderr",
    "stdout",
    "output",
    "content",
    "text",
    "error",
    "result",
    "tool_result",
    "tool_response",
    "response",
)


@dataclass(frozen=True)
class TranscriptRecovery:
    """Result of trying to recover a tool call's full transcript output."""

    text: str | None
    note: str


@dataclass
class _RecoveredOutputTail:
    """Incrementally retain only the useful tail of recovered result text."""

    text: str = ""
    omitted_chars: int = 0
    omitted_lines: int = 0
    omission_is_line_aligned: bool = False

    def append(self, value: str) -> None:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        combined = (
            f"{self.text}{_RECOVERED_OUTPUT_SEPARATOR}{normalized}"
            if self.text
            else normalized
        )
        retain_from = command_output_tail_start(
            combined,
            MAX_RECOVERED_OUTPUT_CHARS,
            COMMAND_OUTPUT_MIN_TAIL_LINES,
        )
        if retain_from > 0:
            omitted = combined[:retain_from]
            self.omitted_chars += retain_from
            self.omitted_lines += omitted.count("\n")
            self.omission_is_line_aligned = omitted.endswith("\n")
            combined = combined[retain_from:]
        self.text = combined

    def render(self) -> str:
        if self.omitted_chars == 0:
            return self.text
        omitted_lines = self.omitted_lines if self.omission_is_line_aligned else None
        marker = command_output_omission_marker(
            self.omitted_chars,
            omitted_lines,
        )
        return f"{marker}\n{self.text}"


def recover_tool_call_output(
    entry: ToolCallEntry,
    *,
    max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES,
) -> TranscriptRecovery:
    """Best-effort transcript recovery for a tool call."""
    tool_use_id = entry.tool_use_id
    if not tool_use_id:
        return TranscriptRecovery(None, "Not recovered: tool use ID unavailable.")

    transcript_path = entry.transcript_path
    if not transcript_path:
        return TranscriptRecovery(None, "Not recovered: transcript unavailable.")

    path = Path(transcript_path).expanduser()
    try:
        size = path.stat().st_size
    except OSError:
        return TranscriptRecovery(None, "Not recovered: transcript file missing.")

    if size > max_transcript_bytes:
        return TranscriptRecovery(
            None,
            "Not recovered: transcript exceeds the 16 MiB scan cap.",
        )

    recovered = _RecoveredOutputTail()
    seen: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if tool_use_id not in line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for mapping in _walk_mappings(payload):
                    if not _references_tool_use_id(mapping, tool_use_id):
                        continue
                    for text in _extract_text_result_fields(mapping):
                        if not text or text in seen:
                            continue
                        seen.add(text)
                        recovered.append(text)
    except OSError:
        return TranscriptRecovery(None, "Not recovered: transcript read failed.")

    if not recovered.text:
        return TranscriptRecovery(
            None,
            "Not recovered: no matching result text found in transcript.",
        )

    if recovered.omitted_chars:
        return TranscriptRecovery(
            recovered.render(),
            "Recovered from transcript; output from the beginning was omitted "
            "while the tail was preserved (64 KiB soft cap).",
        )
    return TranscriptRecovery(recovered.text, "Recovered from transcript.")


def _walk_mappings(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _references_tool_use_id(mapping: dict[str, Any], tool_use_id: str) -> bool:
    for key in ("tool_use_id", "toolUseId", "tool_call_id", "toolCallId", "id"):
        if mapping.get(key) == tool_use_id:
            return True
    return False


def _extract_text_result_fields(mapping: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in _TEXT_RESULT_KEYS:
        if key in mapping:
            parts.extend(_text_values(mapping[key]))
    return parts


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        list_parts: list[str] = []
        for item in value:
            list_parts.extend(_text_values(item))
        return list_parts
    if isinstance(value, dict):
        dict_parts: list[str] = []
        for key in _TEXT_RESULT_KEYS:
            if key in value:
                dict_parts.extend(_text_values(value[key]))
        return dict_parts
    return []
