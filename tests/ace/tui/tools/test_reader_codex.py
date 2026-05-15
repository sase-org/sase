from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.tools import read_tool_calls_for_agent

from ._reader_helpers import (
    _agent,
    _record,
    _tool_result_record,
    _tool_use_record,
    _write_jsonl,
)


def test_read_tool_calls_for_agent_reads_legacy_codex_function_call(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _record(
                runtime="codex",
                source="stream",
                event="FunctionCall",
                tool_use_id="call_legacy",
                tool_name="Read",
                tool_input_summary={"file_path": "src/sase/foo.py"},
                tool_response_summary={},
            )
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "codex"
    assert entry.event == "FunctionCall"
    assert entry.status == "success"
    assert entry.compact_target == "src/sase/foo.py"


def test_read_tool_calls_for_agent_collapses_codex_stream_records(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="item_1",
                runtime="codex",
                source="stream",
                tool_name="Bash",
                tool_input_summary={"command": "/bin/zsh -lc pwd"},
            ),
            _tool_result_record(
                tool_use_id="item_1",
                runtime="codex",
                source="stream",
                tool_name="Bash",
                duration_ms=9,
                tool_input_summary={"command": "/bin/zsh -lc pwd"},
                tool_response_summary={
                    "exit_code": 0,
                    "output_preview": "/tmp/sase-codex-fixture\n",
                    "success": True,
                },
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "codex"
    assert entry.source == "stream"
    assert entry.status == "success"
    assert entry.duration_ms == 9
    assert entry.compact_target == "/bin/zsh -lc pwd"
    assert entry.detail == "exit 0 | /tmp/sase-codex-fixture"


def test_read_tool_calls_for_agent_keeps_same_codex_call_id_in_distinct_sessions(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="item_reused",
                runtime="codex",
                source="stream",
                session_id="thread-a",
            ),
            _tool_result_record(
                tool_use_id="item_reused",
                runtime="codex",
                source="stream",
                session_id="thread-b",
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert [(entry.session_id, entry.status) for entry in entries] == [
        ("thread-a", "pending"),
        ("thread-b", "success"),
    ]


def test_read_tool_calls_for_agent_keeps_reused_codex_ids_per_retry_dir(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "ace-run" / "20260514140000"
    retry_dir = tmp_path / "ace-run" / "20260514140500"
    root_dir.mkdir(parents=True)
    retry_dir.mkdir(parents=True)
    (retry_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "retry_of_timestamp": root_dir.name,
                "retry_chain_root_timestamp": root_dir.name,
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="item_0",
                runtime="codex",
                source="stream",
                recorded_at="2026-05-14T14:00:00+00:00",
                tool_input_summary={"command": "echo root"},
            ),
            _tool_result_record(
                tool_use_id="item_0",
                runtime="codex",
                source="stream",
                recorded_at="2026-05-14T14:00:02+00:00",
                tool_response_summary={"output_preview": "root\n"},
            ),
        ],
    )
    _write_jsonl(
        retry_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="item_0",
                runtime="codex",
                source="stream",
                recorded_at="2026-05-14T14:00:01+00:00",
                tool_input_summary={"command": "echo retry"},
            ),
            _tool_result_record(
                tool_use_id="item_0",
                runtime="codex",
                source="stream",
                recorded_at="2026-05-14T14:00:03+00:00",
                tool_response_summary={"output_preview": "retry\n"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(
        _agent(root_dir, retry_chain_root_timestamp=root_dir.name)
    )

    assert entries is not None
    assert len(entries) == 2
    assert [entry.compact_target for entry in entries] == ["echo root", "echo retry"]
    assert [entry.detail for entry in entries] == ["root", "retry"]
