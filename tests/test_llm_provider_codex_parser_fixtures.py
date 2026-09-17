"""Tests replaying captured Codex CLI NDJSON fixtures through the parser."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

from sase.llm_provider._subprocess import _process_codex_json_line
from sase.llm_provider._tool_calls import _TOOL_CALL_RECORD_REQUIRED_FIELDS

from tests._llm_provider_codex_parser_helpers import _load_fixture_events


def test_codex_stream_fixture_contract_documents_current_tool_shapes() -> None:
    """codex-cli 0.130.0 emits command/file items, not function_call items."""
    events = _load_fixture_events("codex-cli-0.130.0-tools.jsonl")

    tool_items: list[Mapping[str, object]] = []
    for event in events:
        item = event.get("item")
        if (
            event.get("type") in {"item.started", "item.completed"}
            and isinstance(item, Mapping)
            and item.get("type") in {"command_execution", "file_change"}
        ):
            tool_items.append(item)

    command_items = [
        item for item in tool_items if item.get("type") == "command_execution"
    ]
    file_change_items = [
        item for item in tool_items if item.get("type") == "file_change"
    ]
    completed_commands = [
        item for item in command_items if item.get("status") in {"completed", "failed"}
    ]

    assert [event["type"] for event in events[:2]] == ["thread.started", "turn.started"]
    assert {item["status"] for item in command_items} == {
        "in_progress",
        "completed",
        "failed",
    }
    assert {item["status"] for item in file_change_items} == {
        "in_progress",
        "completed",
    }
    assert [item["exit_code"] for item in completed_commands] == [0, 0, 7, 0]
    assert not any(
        isinstance(event.get("item"), Mapping)
        and event["item"].get("type") == "function_call"
        for event in events
    )


def test_codex_parser_processes_captured_tool_fixture_with_artifacts(
    tmp_path: Path,
) -> None:
    """Parser extracts text and writes normalized Codex tool rows."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        for event in _load_fixture_events("codex-cli-0.130.0-tools.jsonl"):
            _process_codex_json_line(
                json.dumps(event),
                assistant_texts,
                True,
                error_events,
            )

    assert assistant_texts == [
        'Final file content:\n\n```text\nbeta\n```\n\n`sh -c "exit 7"` failed with exit code `7`.'
    ]
    assert error_events == []
    with open(tmp_path / "tool_calls.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    assert len(records) == 10
    assert [record["event"] for record in records[:2]] == ["ToolUse", "ToolResult"]
    assert records[0]["tool_name"] == "Bash"
    assert records[1]["tool_response_summary"]["output_preview"] == (
        "/tmp/sase-codex-fixture\n"
    )
    assert records[7]["status"] == "failure"
    assert records[7]["tool_response_summary"]["exit_code"] == 7
    assert all(
        field in record
        for record in records
        for field in _TOOL_CALL_RECORD_REQUIRED_FIELDS
    )


def test_codex_parser_processes_captured_error_fixture() -> None:
    """Captured Codex CLI errors are surfaced through both error channels."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    for event in _load_fixture_events("codex-cli-0.130.0-error.jsonl"):
        _process_codex_json_line(
            json.dumps(event),
            assistant_texts,
            True,
            error_events,
        )

    assert assistant_texts == []
    assert len(error_events) == 2
    assert error_events[0].startswith("[error] ")
    assert error_events[1].startswith("[turn.failed] ")
    assert "codex-mini-latest" in error_events[0]


def test_codex_parser_ignores_synthesized_unknown_item_fixture() -> None:
    """Unknown Codex item shapes are ignored until explicitly normalized."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    for event in _load_fixture_events("synthesized-unknown-item.jsonl"):
        _process_codex_json_line(
            json.dumps(event),
            assistant_texts,
            True,
            error_events,
        )

    assert assistant_texts == []
    assert error_events == []
