"""A Muse reply renders as one timestamped chunk, not one per streamed delta."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
    render_agent_reply_content,
)
from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _envelope(payload_type: str, payload: dict[str, object]) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "event",
                "durability": "durable",
                "payload_type": payload_type,
                "payload_schema_version": 1,
                "payload": payload,
            }
        )
        + "\n"
    )


def _stream_muse(stdout: str) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", stdout],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stream_and_parse_muse_json_output(process, suppress_output=True)


def test_muse_reply_renders_one_divider_for_all_streamed_deltas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    deltas = ["It doesn", "'t replace coding agents — it is `", "sase` — Structured"]
    reply = "".join(deltas)
    command = {"command_id": "cmd-1", "run_stream": {"id": "cmd-1", "kind": "run"}}
    _stream_muse(
        "".join(
            _envelope("run.output.delta", {**command, "text": text}) for text in deltas
        )
        + _envelope("run.terminal.completed", {**command, "text": reply})
    )

    agent = make_agent(status="DONE", artifacts_dir=str(tmp_path))
    renderables = render_agent_reply_content(agent, render_markdown=lambda text: text)

    dividers = [item for item in renderables if isinstance(item, Text)]
    bodies = [item for item in renderables if isinstance(item, str)]
    assert len(dividers) == 1
    assert bodies == [reply]
