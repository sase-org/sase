"""Shared fixtures and helpers for Codex NDJSON parser tests."""

import json
import subprocess
import sys
from pathlib import Path

CODEX_STREAM_FIXTURES = Path(__file__).parent / "fixtures" / "codex_stream"


def _load_fixture_events(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (CODEX_STREAM_FIXTURES / name)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def _start_fixture_codex_process(
    events: list[dict[str, object]],
) -> subprocess.Popen[str]:
    lines = [json.dumps(event) for event in events]
    script = f"import sys\nfor line in {lines!r}:\n    print(line, flush=True)\n"
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
