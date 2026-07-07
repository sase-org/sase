from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.llm_provider._subprocess import (
    _process_codex_json_line,
    _process_json_line,
    _process_opencode_json_line,
    _process_qwen_json_line,
)


def _read_diagnostics(path: Path) -> list[dict[str, object]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.mark.parametrize(
    ("runtime", "handler"),
    [
        (
            "claude",
            lambda line: _process_json_line(line, [], suppress_output=True),
        ),
        (
            "codex",
            lambda line: _process_codex_json_line(line, [], suppress_output=True),
        ),
        (
            "qwen",
            lambda line: _process_qwen_json_line(line, [], suppress_output=True),
        ),
        (
            "opencode",
            lambda line: _process_opencode_json_line(line, [], suppress_output=True),
        ),
    ],
)
def test_process_json_line_records_bounded_decode_diagnostics(
    runtime: str,
    handler: Callable[[str], None],
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": tmpdir}):
            for index in range(6):
                handler(f'{{"bad": {index}')

        diagnostics = _read_diagnostics(Path(tmpdir) / "tool_calls_writer_errors.jsonl")

    assert len(diagnostics) == 5
    assert diagnostics[0]["reason"] == f"{runtime}_stdout_json_decode_error"
    assert diagnostics[0]["line_length"] == len('{"bad": 0')
    assert "raw_preview" in diagnostics[0]
    assert "error" in diagnostics[0]
