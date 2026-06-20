"""Parity gate: the Tools panel stays provider-neutral for ``agy``.

The Antigravity (``agy``) provider streams plain stdout and may write
``tool_calls.jsonl`` only from guarded trajectory extraction. The ACE Agents-tab
Tools panel stays on the provider-neutral artifact contract and must not learn
to scrape ``agy``'s human display text (``live_reply.md`` prose) into fabricated
tool-call rows.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.tools import read_tool_calls_for_agent
from sase.llm_provider._tool_call_agy import (
    AgyTrajectoryStep,
    normalize_agy_trajectory_steps,
)

from ._reader_helpers import (
    _agent,
    _tool_use_record,
    _write_jsonl,
)


def test_agy_run_without_tool_calls_artifact_shows_nothing(tmp_path: Path) -> None:
    """An ``agy`` run writes only ``live_reply.md`` — the panel reads ``None``.

    The reader is the single cross-runtime contract: with no ``tool_calls.jsonl``
    present it returns ``None`` (the Tools panel shows nothing), proving there is
    no ``agy``-specific scraping fallback that mines the plain reply for tools.
    """
    artifacts_dir = tmp_path / "ace-run" / "20260619230000"
    artifacts_dir.mkdir(parents=True)
    # Tool-shaped prose in the plain reply must never become a tool-call row.
    (artifacts_dir / "live_reply.md").write_text(
        "● Running tool: Bash(echo hi)\nfinal agy answer\n",
        encoding="utf-8",
    )

    assert read_tool_calls_for_agent(_agent(artifacts_dir)) is None


def test_tools_panel_contract_is_unchanged_for_agy_runtime(tmp_path: Path) -> None:
    """The panel reads the same normalized contract regardless of runtime.

    There is no ``agy`` source/runtime branch in the reader. If a future
    Antigravity machine-readable contract ever lets SASE emit normalized rows
    (``runtime: "agy"``), they flow through the existing provider-neutral reader
    with no panel changes — this pins that the contract, not display scraping,
    is what the panel consumes.
    """
    artifacts_dir = tmp_path / "ace-run" / "20260619230100"
    _write_jsonl(
        artifacts_dir / "tool_calls.jsonl",
        [
            _tool_use_record(
                tool_use_id="agy-future-call",
                runtime="agy",
                source="stream",
                tool_input_summary={"command": "echo agy"},
            ),
        ],
    )

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert [(entry.runtime, entry.source) for entry in entries] == [("agy", "stream")]


def test_reader_collapses_agy_trajectory_extractor_output(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "ace-run" / "20260619230200"
    records = normalize_agy_trajectory_steps(
        [
            AgyTrajectoryStep(
                1,
                15,
                3,
                _payload("run_command", {"command": "echo agy"}),
            ),
            AgyTrajectoryStep(2, 21, 3, _payload({"stdout": "agy\n"})),
        ],
        conversation_id="agy-conv",
        cwd="/workspace",
    )
    _write_jsonl(artifacts_dir / "tool_calls.jsonl", records)

    entries = read_tool_calls_for_agent(_agent(artifacts_dir))

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.runtime == "agy"
    assert entry.source == "trajectory"
    assert entry.status == "success"
    assert entry.tool_name == "Bash"
    assert entry.tool_input_summary == {"command": "echo agy"}
    assert entry.tool_response_summary["stdout_preview"] == "agy\n"


def _payload(*values: object) -> bytes:
    payload = _field_varint(1, 15)
    for index, value in enumerate(values, start=10):
        if isinstance(value, str):
            data = value.encode("utf-8")
        else:
            data = json.dumps(value, sort_keys=True).encode("utf-8")
        payload += _field_bytes(index, data)
    return payload


def _field_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            encoded.append(byte | 0x80)
        else:
            encoded.append(byte)
            return bytes(encoded)
