"""Shared fixtures and helpers for Muse provider tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from sase.llm_provider.muse import MuseProvider

_FIXTURES = Path(__file__).parent / "fixtures"
_READ_TOOL_FIXTURE = _FIXTURES / "muse_exec_read_tool_R708.1.jsonl"
_WRITE_BASH_FIXTURE = _FIXTURES / "muse_exec_write_bash_tools_R708.1.jsonl"

_MUSE_MODELS = [
    "muse-spark-1.3",
    "muse-spark-1.3-contributor",
    "muse-spark-1.2",
    "muse-spark-1.2-contributor",
    "muse-spark-1.1",
]


def _run_fixture_stream(
    payload: str,
    *,
    exit_code: int = 0,
    stderr: str = "",
    suppress_output: bool = True,
) -> tuple[str, str, int, dict[str, int]]:
    """Replay *payload* on a real subprocess's stdout and parse the stream."""
    script = (
        "import sys\n"
        "sys.stdout.write(sys.argv[1])\n"
        "sys.stderr.write(sys.argv[2])\n"
        "sys.exit(int(sys.argv[3]))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, payload, stderr, str(exit_code)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return stream_and_parse_muse_json_output(process, suppress_output=suppress_output)


def _envelope(payload_type: str, payload: dict[str, object], **envelope: object) -> str:
    record = {
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": payload_type,
        "payload_schema_version": 1,
        "payload": payload,
    }
    record.update(envelope)
    return json.dumps(record) + "\n"


def _invoke_and_capture(
    provider: MuseProvider,
    **invoke_kwargs: object,
) -> tuple[list[str], dict[str, object]]:
    """Invoke *provider* against mocked subprocess plumbing and return the argv."""
    with (
        patch(
            "sase.llm_provider.muse.stream_and_parse_muse_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.muse.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.muse.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("response", "", 0, {})
        provider.invoke(
            "test prompt",
            model_tier="large",
            suppress_output=True,
            **invoke_kwargs,  # type: ignore[arg-type]
        )
        return list(mock_popen.call_args.args[0]), dict(mock_popen.call_args.kwargs)


def _delta(text: str, command_id: str | None = "cmd-1") -> str:
    payload: dict[str, object] = {"kind": "run_output_delta", "text": text}
    if command_id is not None:
        payload["command_id"] = command_id
        payload["run_stream"] = {"id": command_id, "kind": "run"}
    return _envelope("run.output.delta", payload, record_type="status")


def _terminal(text: str, command_id: str | None = "cmd-1") -> str:
    payload: dict[str, object] = {"terminal": "completed", "text": text}
    if command_id is not None:
        payload["command_id"] = command_id
    return _envelope("run.terminal.completed", payload)


def _read_timestamps(tmp_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (tmp_path / "live_reply_timestamps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
